import os
import json
import re
import tldextract
import tempfile
import requests
from flask import Flask, request, g, jsonify, make_response
from dbconf import database_connect
from utils import get_existing_domain_id, query_to_object
from report import generate_site_diff_report
app = Flask(__name__)

dbdesc = json.load(open('dbdesc.json', 'r'))

UPLOAD_PATH_PREFIX = os.path.join('files', 'screenshots') + os.path.sep
# UPLOAD_PATH_PREFIX = os.path.sep + os.path.join('fs', 'compatdataviewer-files') + os.path.sep
if not os.path.exists(UPLOAD_PATH_PREFIX):
    os.mkdir(UPLOAD_PATH_PREFIX)

AWCY_DATA_URLPREFIX = 'http://arewecompatibleyet.com/data/'

@app.before_request
def before_req():
    # prepare talking to the database before every request..
    g.con, g.cur_1, g.cur_2 = database_connect()

@app.teardown_request
def teardown_req(response):
    # ..but be polite enough to close it afterwards
    db = getattr(g, 'con', None)
    if db:
        db.close()


def cors_friendly(f):
    """This decorator adds CORS headers"""
    def decorated_function(*args, **kwargs):
        resp = make_response(f(*args, **kwargs))
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    return decorated_function


"""
/*
 URLs we support
 /data/domain.tld - JSON data
 /screenshots/domain.tld - JSON data (list of screenshots w/UA, meta data)
 /screenshot/domain.tld/filename.png -
    screenshot (maps to /files/screenshots/domain.tld/filename.png)
  (should be handled with --static-map ..)'

/bug/bug_id - Regression result report for given bug

/list/awcy_list_shortname - gives a "diff" view for all sites on AWCY list (#TODO: add more tables that test_data)

/diff/domain.tld - gets results from different UA types, printes out differences only (#TODO)

/time/domain.tld - gives evolution over time - diffs per UA type during last 6 months or so (#TODO)

 MAYBE
 /contacts/domain.tld
 /comments/domain.tld
 - or merge them into the /data/domain.tld info?


To ADD data:
POST /data/domain.tld

Basically all URLs have the structure
    "topic" / "domain.tld" / optional specifics

We may add support for query string arguments like ?timerange or ?limits

*/

/*
POST data structure:
data is posted for a single domain - given in _URL_
data is typically posted per UA. Multiple UAs may be tested at once.

This means we'll have
POST /post/domain.tld

data={
    "uastring":{
        "engine": {
            redirects: [ 'url1', 'url2'..],
            final_url: '',
            css_problems: [
                {'file':'', 'selector':'', 'property':'', 'value': ''... ],
            js_problems: [ {stack:'', message:''}, ... ],
            plugin_results: { ... },
            state: 1|0,
            failing_because: ["style_problems", "old_brightcove", ...],
                "regression_results": [
                    {"bug_id":"wc1066", "result":0,"screenshot":"file_name"} ]
        }
    },
    "initial_url": "..."
}

All posts that include images must also have this:

file_desc:{
    "file_name":{
        "engine": "...",
        "ua": "...",
        "title": "..for 'special' screenshots that have a description"
    }
}

on the other hand, we can have simpler posts for comments,
contact data and such:

POST /contacts/domain.tld
POST /comments/domain.tld =>
post field names map directly to table names:
tables.contacts etc lists the fields
"""


@app.route('/', methods=['GET'])
def nothing():
    return 'Nothing to see here (what are you looking for?)'


@app.route('/<topic>/<domain>', methods=['GET'])
@cors_friendly
def dataviewer(topic, domain):
    recent_datasets = []
    if (topic == 'list' or topic == 'diff') and domain != '':
        if topic == 'list':
            # "domain" is a misnomer in list mode, should be 'list'
            # we want to load a list of sites from AWCY data
            # and generate a report
            req = requests.get('%s%s.json' % (AWCY_DATA_URLPREFIX, domain))
            listdata = req.json()['data']
        else:
            # domain is the domain we want to diff..
            listdata = [domain]
        report = generate_site_diff_report(listdata, g.cur_1)
        return jsonify(**report)
    if topic == 'bug' and re.search('^(moz|wc)\d+$', domain):
        bug_id = domain
        # import pdb
        # pdb.set_trace()
        # We're looking for regression results for given bug
        # Two possible sources: regression_results table
        # OR if we have JSON data linking bug to a specific
        # table field, that table. We want to output lists of
        # [{date, result, ua, engine, url, hostname, screenshot, data_set?}]
        results = {bug_id:[]}
        used_uas = set()
        used_datasets = set()
        query_to_object('SELECT date,result,screenshot,data_set,site,ua,engine FROM regression_results WHERE bug_id = "%s" LIMIT 10' % bug_id, results, bug_id)
        bug_data_file = os.path.join('data', '%s.json' % bug_id )
        if os.path.exists(bug_data_file):
            f = open(bug_data_file, 'r')
            bug_data = json.load(f)
            f.close()
            domain = normalize_domain(bug_data['hostname'])
            domain_id = get_existing_domain_id(domain, False)
            # We now have an array of fields considered relevant for this bug
            # we look up the last x values from those fields..
            if domain_id:
                for field_details in bug_data['field_list']:
                    query_to_object('SELECT data_set, ua, engine, %s  FROM %s WHERE site = %s LIMIT 10 ' % (field_details['field'], field_details['table'], domain_id), results, "%s.%s" % (field_details['table'],field_details['field']))
            # We need "supplementary" data: UA strings, screenshot URLs.. Will see..
            for category in results:
                for result in results[category]:
                    if 'data_set' in result:
                        used_datasets.add(result['data_set'])
                    if 'ua' in result:
                        used_uas.add(result['ua'])
            if used_datasets:
                query_to_object('SELECT * FROM testdata_sets WHERE id IN (%s)' % (', '.join(str(s) for s in used_datasets)), results, 'datasets' )
            if used_uas:
                query_to_object('SELECT * FROM uastrings WHERE id IN (%s)' % (', '.join(str(s) for s in used_uas)), results, 'uastrings' )
        return jsonify(**results)

    if is_number(domain):
        # we're looking up information about a test data set
        recent_datasets = [domain]
        output = {'dataset': domain}
    else:
        try:
            domain = normalize_domain(domain)
        except Exception, e:
            print(e)
            return ('Name of site not valid? Processing it causes an error: %s'
                    % e, 500)
        domain_id = get_existing_domain_id(domain, False)
        if not domain_id:
            return ('No data found for this site', 404)
        output = {'domain': domain, 'id': domain_id}
        query_to_object(
            'SELECT * FROM testdata_sets WHERE site = %s ORDER BY id DESC LIMIT 4' % domain_id, output, 'datasets')
    # we need a list of datasets to select related screenshots, CSS problems,
    # JS problems and test data..
        for the_set in output['datasets']:
            recent_datasets.append(the_set['id'])
    if topic == 'data':
        if len(recent_datasets):
            query_to_object('SELECT * FROM screenshots WHERE data_set IN (%s) ORDER BY id DESC LIMIT 4' %
                            json.dumps(recent_datasets)[1:-1],
                            output, 'screenshots', screenshot_url)
            query_to_object('SELECT * FROM css_problems WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' %
                            json.dumps(recent_datasets)[1:-1],
                            output, 'css_problems')
            query_to_object('SELECT * FROM js_problems WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' %
                            json.dumps(recent_datasets)[1:-1],
                            output, 'js_problems')
            query_to_object('SELECT * FROM test_data WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' %
                            json.dumps(recent_datasets)[1:-1],
                            output, 'test_data')
            query_to_object('SELECT * FROM redirects WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' %
                            json.dumps(recent_datasets)[1:-1],
                            output, 'redirects')
            query_to_object('SELECT * FROM regression_results WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' %
                            json.dumps(recent_datasets)[1:-1],
                            output, 'regression_results')
            # We also need a list of the UA strings used in these data sets..
            all_ua_ids = set()
            for row in output['screenshots']:
                all_ua_ids.add(row['ua'])
            for row in output['test_data']:
                all_ua_ids.add(row['ua'])
            for row in output['css_problems']:
                all_ua_ids.add(row['ua'])
            for row in output['js_problems']:
                all_ua_ids.add(row['ua'])
            for row in output['redirects']:
                all_ua_ids.add(row['ua'])
            for row in output['regression_results']:
                all_ua_ids.add(row['ua'])
            query_to_object('SELECT DISTINCT id, ua FROM uastrings WHERE id IN (%s) ORDER BY id ASC' % json.dumps(
                list(all_ua_ids))[1:-1], output, 'uastrings', add_ua_desc)
    elif topic == 'comments':
        query_to_object(
            'SELECT * FROM comments WHERE site = %s LIMIT 15 ORDER BY id DESC' % domain_id, output, 'comments')
    elif topic == 'contacts':
        query_to_object(
            'SELECT * FROM contacts WHERE site = %s LIMIT 15 ORDER BY id DESC' % domain_id, output, 'contacts')
    return jsonify(**output)


@app.route('/testform', methods=['GET'])
def testform():
    return '<html><form method="post" action="http://localhost:8000/data/example.com" enctype="multipart/form-data">Data JSON:<br><textarea name="data"></textarea><br>File desc JSON:<br><textarea name="file_desc"></textarea><br>Screenshots:<br><input type="file" name="screenshot"><br><input type="file" name="screenshot"><br><input type="submit">'


@app.route('/<topic>/<domain>', methods=['POST'])
def datasaver(topic, domain):
    con = g.con
    cur_2 = g.cur_2
    if topic == '' or domain == '':
        return ('Required information missing: site etc.', 500)
    # by this point we have a "topic" ('data', 'screenshots', 'contacts' etc)
    # and we have a presumed domain name. Let's check if the domain name is
    # tracked already..
    try:
        domain = normalize_domain(domain)
    except Exception, e:
        print(e)
        return ('Name of site not valid? Processing it causes an error: %s'
                % e, 500)
    domain_id = get_existing_domain_id(domain) # this will add domain to DB if not already tracked
    try:
        post_data = json.loads(request.form['data'])
        initial_url = request.form['initial_url']
        # now we have a "set" of data for this site, with various UA strings and maybe engines
        # we register a "dataset id" for this submit by creating a row in the
        # testdata_sets table
        cur_2.execute(
            'INSERT INTO testdata_sets (site, url) VALUES (%s, %s)', (domain_id, initial_url))
        con.commit()
        dataset_id = cur_2.lastrowid
        for uastring in post_data:
            uastring_id = get_existing_ua_id_or_insert(uastring)
            for engine in post_data[uastring]:
                print('Now processing dataset %s' % dataset_id)
                # Fill tables.. Now "test_data"
                insert_data = {
                    'data_set': dataset_id, 'site': domain_id, 'engine': engine, 'ua': uastring_id}
                for prop in post_data[uastring][engine]:
                    if prop in dbdesc['test_data'] and prop != 'id':
                        if type(post_data[uastring][engine][prop]) == list:
                            insert_data[prop] = '\t'.join(
                                post_data[uastring][engine][prop])
                        else:
                            insert_data[prop] = post_data[
                                uastring][engine][prop]
                other_plugin_data = {}
                if 'plugin_results' in post_data[uastring][engine]:
                    for prop in post_data[uastring][engine]['plugin_results']:
                        if prop in dbdesc['test_data']:
                            insert_data[prop] = post_data[uastring][
                                engine]['plugin_results'][prop]
                        else:
                            other_plugin_data[prop] = post_data[
                                uastring][engine]['plugin_results'][prop]
                    insert_data['other_plugin_data'] = json.dumps(
                        other_plugin_data)

                    # get property names from insert_data
                    obj_to_table(insert_data, 'test_data', cur_2)

                # Fill tables.. Now "css_problems"
                if 'css_problems' in post_data[uastring][engine] and post_data[uastring][engine]['css_problems']:
                    the_query = 'INSERT INTO css_problems (data_set, ua, engine, site, file, selector, property, value) VALUES (%s, %s, "%s", %s, %%(file)s, %%(selector)s, %%(property)s, %%(value)s)' % (
                        dataset_id, uastring_id, engine, domain_id)
                    cur_2.executemany(
                        the_query, post_data[uastring][engine]['css_problems'])
                # Fill tables.. Now "js_problems"
                if 'js_problems' in post_data[uastring][engine] and post_data[uastring][engine]['js_problems']:
                    the_query = 'INSERT INTO js_problems (data_set, ua, engine, site, stack, message) VALUES (%s, %s, "%s", %s, %%(stack)s, %%(message)s)' % (
                        dataset_id, uastring_id, engine, domain_id)
                    cur_2.executemany(
                        the_query, post_data[uastring][engine]['js_problems'])
                # Fill tables.. Now "redirects"
                if 'redirects' in post_data[uastring][engine] and post_data[uastring][engine]['redirects']:
                    the_query = 'INSERT INTO redirects (data_set, ua, engine, site, urls) VALUES (%s, %s, "%s", %s, "%s")' % (
                        dataset_id, uastring_id, engine, domain_id, '\t'.join(post_data[uastring][engine]['redirects']))
                    cur_2.execute(the_query)
                # Fill tables.. Now "regression_results"
                # "regression_results": "site","ua","engine","bug_id","result","screenshot"
                # pdb.set_trace()
                if 'regression_results' in post_data[uastring][engine] and post_data[uastring][engine]['regression_results']:
                    for reg_res in post_data[uastring][engine]['regression_results']:
                        reg_res['data_set'] = dataset_id
                        reg_res['ua'] = uastring_id
                        reg_res['engine'] = engine
                        # TODO: add "comment" if "result" is text rather than
                        # true/false?
                        the_screenshot = reg_res['screenshot']
                        del reg_res['screenshot']
                        insert_id = obj_to_table(
                            reg_res, 'regression_results', cur_2)
                        regression_insert_ids[insert_id] = the_screenshot
    except Exception, e:
        return ('Problem with form data? Processing it causes an error: %s'
                % e, 500)

    domain_id = get_existing_domain_id(domain)
    dataset_id = -1
    # This list will be used to map regressions and screenshots
    regression_insert_ids = {}
    # If topic is "data" we have a POST form field called data
    # which is actually a chunk of JSON. It requires some parsing and
    # massage to throw the data into the right table(s)..
    if topic == 'data' and 'data' in request.form and request.form['data']:
        try:
            post_data = json.loads(request.form['data'])
            initial_url = request.form['initial_url']
            # now we have a "set" of data for this site,
            # with various UA strings and maybe engines
            # we register a "dataset id" for this submit by creating a row in
            # the testdata_sets table
            cur_2.execute(
                'INSERT INTO testdata_sets (site, url) VALUES (%s, %s)',
                (domain_id, initial_url))
            con.commit()
            dataset_id = cur_2.lastrowid
            for uastring in post_data:
                uastring_id = get_existing_ua_id_or_insert(uastring)
                for engine in post_data[uastring]:
                    print('Now processing dataset %s' % dataset_id)
                    # Fill tables.. Now "test_data"
                    insert_data = {
                        'data_set': dataset_id,
                        'site': domain_id,
                        'engine': engine,
                        'ua': uastring_id}
                    for prop in post_data[uastring][engine]:
                        if prop in dbdesc['test_data'] and prop != 'id':
                            if type(post_data[uastring][engine][prop]) == list:
                                insert_data[prop] = '\t'.join(
                                    post_data[uastring][engine][prop])
                            else:
                                insert_data[prop] = post_data[
                                    uastring][engine][prop]
                    other_plugin_data = {}
                    if 'plugin_results' in post_data[uastring][engine]:
                        for prop in post_data[uastring][engine]['plugin_results']:
                            if prop in dbdesc['test_data']:
                                insert_data[prop] = post_data[uastring][
                                    engine]['plugin_results'][prop]
                            else:
                                other_plugin_data[prop] = post_data[
                                    uastring][engine]['plugin_results'][prop]
                        insert_data['other_plugin_data'] = json.dumps(
                            other_plugin_data)

                        # get property names from insert_data
                        obj_to_table(insert_data, 'test_data', cur_2)

                    # Fill tables.. Now "css_problems"
                    if 'css_problems' in post_data[uastring][engine]:
                        the_query = 'INSERT INTO css_problems (data_set, ua, engine, site, file, selector, property, value) VALUES (%s, %s, "%s", %s, %%(file)s, %%(selector)s, %%(property)s, %%(value)s)' % (
                            dataset_id, uastring_id, engine, domain_id)
                        cur_2.executemany(
                            the_query, post_data[uastring][engine]['css_problems'])
                    # Fill tables.. Now "js_problems"
                    if 'js_problems' in post_data[uastring][engine]:
                        the_query = 'INSERT INTO js_problems (data_set, ua, engine, site, stack, message) VALUES (%s, %s, "%s", %s, %%(stack)s, %%(message)s)' % (
                            dataset_id, uastring_id, engine, domain_id)
                        cur_2.executemany(
                            the_query, post_data[uastring][engine]['js_problems'])
                    # Fill tables.. Now "redirects"
                    if 'redirects' in post_data[uastring][engine]:
                        the_query = 'INSERT INTO redirects (data_set, ua, engine, site, urls) VALUES (%s, %s, "%s", %i, "%%s")' % (
                            dataset_id, uastring_id, engine, site)
                        cur_2.executemany(
                            the_query, '\t'.join(post_data[uastring][engine]['redirects']))
                    # Fill tables.. Now "regression_results"
                    # "regression_results": "site","ua","engine","bug_id","result","screenshot"
                    # pdb.set_trace()
                    if 'regression_results' in post_data[uastring][engine]:
                        for reg_res in post_data[uastring][engine]['regression_results']:
                            reg_res['data_set'] = dataset_id
                            reg_res['ua'] = uastring_id
                            reg_res['engine'] = engine
                            # TODO: add "comment" if "result" is text rather
                            # than true/false?
                            the_screenshot = reg_res['screenshot']
                            del reg_res['screenshot']
                            insert_id = obj_to_table(
                                reg_res, 'regression_results', cur_2)
                            regression_insert_ids[insert_id] = the_screenshot

        except Exception, e:
            print(e)
    elif topic == 'contacts' or topic == 'comments':
        insert_data, other = filter_props(request.form, dbdesc[topic])
        obj_to_table(insert_data, topic, cur_2)

    con.commit()

    # Handle file uploads
    screenshots = request.files.getlist('screenshot')
    if(len(screenshots)):
        file_desc = json.loads(request.form['file_desc'])
        for file_obj in screenshots:
            print('Receiving %s file' % file_obj.mimetype)
            if 'image/' not in file_obj.mimetype:
                continue
            target_filepath = os.path.join(UPLOAD_PATH_PREFIX, domain)
            print(target_filepath)
            if not os.path.exists(target_filepath):
                os.mkdir(target_filepath)
            # pdb.set_trace()
            if file_obj.filename in file_desc:
                uastring_id = get_existing_ua_id_or_insert(
                    file_desc[file_obj.filename]['ua'])
                if dataset_id == -1:
                    # testdata_sets: site, UA id, engine, URL
                    insert_data = {
                        'site': domain_id,
                        'url': post_data[file_desc[file_obj.filename]['ua']][
                            file_desc[file_obj.filename]['engine']][
                            'final_url']}
                    obj_to_table(insert_data, 'testdata_sets', cur_2)
                    con.commit()
                    dataset_id = cur_2.lastrowid
                extension = os.path.splitext(file_obj.filename)[1]
                target_filename = tempfile.NamedTemporaryFile(
                    delete=False,
                    prefix=str(domain_id) + '_',
                    suffix=extension, dir=target_filepath)
                # secure_filename(file_obj.filename)
                # screenshots: data_set, file
                img_insert_id = obj_to_table(
                    {'data_set': dataset_id,
                     'ua': uastring_id,
                     'engine': file_desc[file_obj.filename]['engine'],
                     'file': os.path.basename(target_filename.name)},
                    'screenshots', cur_2)
                file_obj.save(target_filename.name)

                if len(regression_insert_ids.keys()):
                    # update regression_results to set screenshot field
                    for this_reg_ins_id in regression_insert_ids.keys():
                        if regression_insert_ids[this_reg_ins_id] == file_obj.filename:
                            cur_2.execute('UPDATE regression_results SET screenshot = %s WHERE id = %s' % (
                                img_insert_id, this_reg_ins_id))
                con.commit()

            else:
                return ('missing file details for %s' % file_obj.filename, 500)
    return 'Done'


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def filter_props(incoming_obj, prop_list, outgoing_obj={}, other_obj={}):
    for prop in incoming_obj:
        if prop in prop_list:
            outgoing_obj[prop] = incoming_obj[prop]
        else:
            other_obj[prop] = incoming_obj[prop]
    return outgoing_obj, other_obj


def obj_to_table(insert_data, table, cur_2):
    # get property names from insert_data
    the_query = ('INSERT INTO %s (`' % table) + '`, `'.join(insert_data.keys()
                                                            ) + '`) VALUES (%(' + (')s, %('.join(insert_data.keys())) + ')s)'
    cur_2.execute(the_query, insert_data)
    return cur_2.lastrowid

# http://stackoverflow.com/questions/6618344/python-mysqldb-and-escaping-table-names
# ??

def get_existing_ua_id_or_insert(datastr):
    g.cur_1.execute('SELECT id FROM uastrings WHERE ua LIKE %s',  (datastr,))
    if g.cur_1.rowcount > 0:
        row = g.cur_1.fetchone()
        datastr_id = row['id']
    else:
        g.cur_2.execute('INSERT INTO uastrings (ua) VALUES (%s)',  (datastr,))
        g.con.commit()
        datastr_id = g.cur_2.lastrowid
    return datastr_id


# Some methods to "massage" data from the database for presentation

def screenshot_url(row):
    url_parts = request.url.split('/')
    # replace the 'topic' with the word 'screenshot'
    url_parts[3] = 'screenshot'
    row['file'] = '%s/%s' % ('/'.join(url_parts), row['file'])
    return row


def add_ua_desc(row):
    row['human_desc'] = describe_ua(row['ua'])
    return row


def sanitize(dirty_html):
    dirty_html = dirty_html.replace('&', '&amp;')
    dirty_html = dirty_html.replace('<', '&lt;')
    dirty_html = dirty_html.replace('>', '&gt;')
    dirty_html = dirty_html.replace('"', '&quot;')
    return dirty_html


def normalize_domain(domain):
    tmp = tldextract.extract('http://%s' % domain)
    # we remove "meaningless-ish" prefixes only
    if not tmp.subdomain in ['www', '']:
        tmp = '%s.%s.%s' % (tmp.subdomain, tmp.domain, tmp.suffix)
    else:
        tmp = '%s.%s' % (tmp.domain, tmp.suffix)
    return tmp


def describe_ua(uastr):
    # This will never be perfect. Just so you know I know that..
    name = ''
    platform = ''
    version = ''
    if 'Firefox' in uastr and 'like Gecko' not in uastr:
        name = 'Firefox'
    elif 'Chrome' in uastr:
        name = 'Chrome'
    elif 'MSIE' in uastr > -1 or 'Trident' in uastr:
        name = 'IE'
    elif 'Opera' in uastr:
        name = 'Opera'
    elif 'Safari' in uastr:
        name = 'Safari'

    if 'Mobile' in uastr:
        if 'Android' in uastr:
            platform = 'Android'
        else:
            platform = 'OS' if name == 'Firefox' else 'Mobile'
    elif 'Tablet' in uastr:
        platform = 'Tablet'
    else:
        platform = 'Desktop'
    # version
    v = re.search(r"(Firefox\/|Chrome\/|rv:|Version\/)(\d+)", uastr)
    if v:
        version = v.groups()[1]
    return "%s%s%s" % (name, platform, version)


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    print('Serving on port %s' % port)
    app.run('0.0.0.0', port=port)

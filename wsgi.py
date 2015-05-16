import os, json, re, glob, sys, mimetypes, tldextract, tempfile
from flask import Flask, request, session, g, redirect, url_for, jsonify, logging
from werkzeug import secure_filename
#from wsgiref.simple_server import make_server
#from cgi import parse_qs, escape
from dbconf import database_connect

import pdb

app = Flask(__name__)

dbdesc = json.load(open('dbdesc.json', 'r'))

UPLOAD_PATH_PREFIX = os.path.join('files', 'screenshots') + os.path.sep
#UPLOAD_PATH_PREFIX = os.path.sep + os.path.join('fs', 'compatdataviewer-files') + os.path.sep
if not os.path.exists(UPLOAD_PATH_PREFIX):
  os.mkdir(UPLOAD_PATH_PREFIX)
# prepare talking to the database before every request..
@app.before_request
def before_req():
  g.con, g.cur_1, g.cur_2 = database_connect()
# ..but be polite enough to close it afterwards
@app.teardown_request
def teardown_req(response):
  db = getattr(g, 'con', None)
  if db:
    db.close()

"""
/*
 URLs we support
 /data/domain.tld - JSON data
 /screenshots/domain.tld - JSON data (list of screenshots w/UA, meta data)
 /screenshot/domain.tld/filename.png - screenshot (maps to /files/screenshots/domain.tld/filename.png)
  (should be handled with --static-map ..)
 MAYBE
 /contacts/domain.tld
 /comments/domain.tld
 - or merge them into the /data/domain.tld info?

To ADD data:
POST /data/domain.tld

Basically all URLs have the structure "topic" / "domain.tld" / optional specifics

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
            css_problems: [ {'file':'', 'selector':'', 'property':'', 'value': ''... ],
            js_problems: [ {stack:'', message:''}, ... ],
            plugin_results: { ... },
            state: 1|0,
            failing_because: ["style_problems", "old_brightcove", ...],
            "regression_results": [ {"bug_id":"wc1066", "result":0,"screenshot":"file_name"} ]
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

on the other hand, we can have simpler posts for comments, contact data and such:

POST /contacts/domain.tld
POST /comments/domain.tld =>
post field names map directly to table names:
tables.contacts etc lists the fields


  """

@app.route('/', methods = ['GET'])
def nothing():
  return 'Nothing to see here (what are you looking for?)'

@app.route('/<topic>/<domain>', methods = ['GET'])
def dataviewer(topic, domain):
  recent_datasets = []
  if is_number(domain):
    # we're looking up information about a test data set
    recent_datasets = [domain]
    output = {'dataset': domain}
  else:
    try:
      domain = normalize_domain(domain)
    except Exception, e:
      print(e)
      return ('Name of site not valid? Processing it causes an error: %s' % e, 500)
    domain_id = get_existing_domain_id(domain, False)
    if not domain_id:
      return ('No data found for this site', 404)
    output = {'domain':domain, 'id':domain_id }
    query_to_object('SELECT * FROM testdata_sets WHERE site = %s ORDER BY id DESC LIMIT 4' % domain_id, output, 'datasets')
  # we need a list of datasets to select related screenshots, CSS problems, JS problems and test data..
    for the_set in output['datasets']:
      recent_datasets.append(the_set['id'])
  if topic == 'data':
    if len(recent_datasets):
      query_to_object('SELECT * FROM screenshots WHERE data_set IN (%s) ORDER BY id DESC LIMIT 4' % json.dumps(recent_datasets)[1:-1], output, 'recent_screenshots', screenshot_url)
      query_to_object('SELECT * FROM css_problems WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' % json.dumps(recent_datasets)[1:-1], output, 'recent_css_problems')
      query_to_object('SELECT * FROM js_problems WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' % json.dumps(recent_datasets)[1:-1], output, 'recent_js_problems')
      query_to_object('SELECT * FROM test_data WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' % json.dumps(recent_datasets)[1:-1], output, 'recent_other_problems')
      query_to_object('SELECT * FROM redirects WHERE data_set IN (%s) ORDER BY id DESC LIMIT 25' % json.dumps(recent_datasets)[1:-1], output, 'redirects')
      # We also need a list of the UA strings used in these data sets..
      all_ua_ids = set([])
      for row in output['recent_screenshots']:
        all_ua_ids.add(row['ua'])
      for row in output['recent_other_problems']:
        all_ua_ids.add(row['ua'])
      for row in output['recent_css_problems']:
        all_ua_ids.add(row['ua'])
      for row in output['recent_js_problems']:
        all_ua_ids.add(row['ua'])
      for row in output['redirects']:
        all_ua_ids.add(row['ua'])
      query_to_object('SELECT DISTINCT id, ua FROM uastrings WHERE id IN (%s) ORDER BY id ASC' % json.dumps(list(all_ua_ids))[1:-1], output, 'uastrings', add_ua_desc)
  elif topic == 'comments':
    query_to_object('SELECT * FROM comments WHERE site = %s LIMIT 15 ORDER BY id DESC' % domain_id, output, 'comments')
  elif topic == 'contacts':
    query_to_object('SELECT * FROM contacts WHERE site = %s LIMIT 15 ORDER BY id DESC' % domain_id, output, 'contacts')
  return jsonify(**output)

@app.route('/testform', methods = ['GET'])
def testform():
  return '<html><form method="post" action="http://localhost:8000/data/example.com" enctype="multipart/form-data">Data JSON:<br><textarea name="data"></textarea><br>File desc JSON:<br><textarea name="file_desc"></textarea><br>Screenshots:<br><input type="file" name="screenshot"><br><input type="file" name="screenshot"><br><input type="submit">';

@app.route('/<topic>/<domain>', methods = ['POST'])
def datasaver(topic, domain):
  output=[]
  con = g.con
  cur_1 = g.cur_1
  cur_2 = g.cur_2
  if topic == '' or domain == '':
    return ('Required information missing: site etc.', 500)
  # by this point we have a "topic" ('data', 'screenshots', 'contacts' etc)
  # and we have a presumed domain name. Let's check if the domain name is
  # tracked already..
  try:
    domain = normalize_domain(domain)
  except Exception, e:
    return ('Name of site not valid? Processing it causes an error: %s' % e, 500)

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
      # now we have a "set" of data for this site, with various UA strings and maybe engines
      # we register a "dataset id" for this submit by creating a row in the testdata_sets table
      cur_2.execute('INSERT INTO testdata_sets (site, url) VALUES (%s, %s)', (domain_id, initial_url))
      con.commit()
      dataset_id = cur_2.lastrowid
      for uastring in post_data:
        uastring_id = get_existing_ua_id_or_insert(uastring)
        for engine in post_data[uastring]:
          print('Now processing dataset %s' % dataset_id)
          # Fill tables.. Now "test_data"
          insert_data = {'data_set':dataset_id, 'site':domain_id, 'engine': engine, 'ua': uastring_id}
          for prop in post_data[uastring][engine]:
            if prop in dbdesc['test_data'] and prop != 'id':
              if type(post_data[uastring][engine][prop]) == list:
                insert_data[prop] = '\t'.join(post_data[uastring][engine][prop])
              else:
                insert_data[prop] = post_data[uastring][engine][prop]
          other_plugin_data = {}
          if 'plugin_results' in post_data[uastring][engine]:
            for prop in post_data[uastring][engine]['plugin_results']:
              if prop in dbdesc['test_data']:
                insert_data[prop] = post_data[uastring][engine]['plugin_results'][prop]
              else:
                other_plugin_data[prop] = post_data[uastring][engine]['plugin_results'][prop]
            insert_data['other_plugin_data'] = json.dumps(other_plugin_data)

            # get property names from insert_data
            obj_to_table(insert_data, 'test_data', cur_2)

          # Fill tables.. Now "css_problems"
          if 'css_problems' in post_data[uastring][engine]:
            the_query = 'INSERT INTO css_problems (data_set, ua, engine, file, selector, property, value) VALUES (%s, %s, "%s", %%(file)s, %%(selector)s, %%(property)s, %%(value)s)' % (dataset_id,uastring_id,engine)
            cur_2.executemany(the_query, post_data[uastring][engine]['css_problems'])
          # Fill tables.. Now "js_problems"
          if 'js_problems' in post_data[uastring][engine]:
            the_query = 'INSERT INTO js_problems (data_set, ua, engine, stack, message) VALUES (%s, %s, "%s", %%(stack)s, %%(message)s)' % (dataset_id,uastring_id,engine)
            cur_2.executemany(the_query, post_data[uastring][engine]['js_problems'])
          # Fill tables.. Now "redirects"
          if 'redirects' in post_data[uastring][engine]:
            the_query = 'INSERT INTO redirects (data_set, ua, engine, urls) VALUES (%s, %s, "%s", %%s)' % (dataset_id, uastring_id, engine )
            cur_2.executemany(the_query, '\t'.join(post_data[uastring][engine]['redirects']))
          # Fill tables.. Now "regression_results"
          # "regression_results": "site","ua","engine","bug_id","result","screenshot"
          #pdb.set_trace()
          if 'regression_results' in post_data[uastring][engine]:
            for reg_res in post_data[uastring][engine]['regression_results']:
              reg_res['data_set'] = dataset_id
              reg_res['ua'] = uastring_id
              reg_res['engine'] = engine
              # TODO: add "comment" if "result" is text rather than true/false?
              the_screenshot = reg_res['screenshot']
              del reg_res['screenshot']
              insert_id = obj_to_table(reg_res, 'regression_results', cur_2)
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
      #pdb.set_trace()
      if file_obj.filename in file_desc:
        uastring_id = get_existing_ua_id_or_insert(file_desc[file_obj.filename]['ua'])
        if dataset_id == -1:
          # testdata_sets: site, UA id, engine, URL
          insert_data = {'site': domain_id, 'url': post_data[file_desc[file_obj.filename]['ua']][file_desc[file_obj.filename]['engine']]['final_url']}
          obj_to_table(insert_data, 'testdata_sets', cur_2)
          con.commit()
          dataset_id = cur_2.lastrowid
        extension = os.path.splitext(file_obj.filename)[1]
        target_filename = tempfile.NamedTemporaryFile(delete=False, prefix=str(domain_id)+'_', suffix=extension, dir=target_filepath )
        # secure_filename(file_obj.filename)
        # screenshots: data_set, file
        insert_id = obj_to_table({"data_set": dataset_id, 'ua': uastring_id, 'engine': file_desc[file_obj.filename]['engine'], "file": os.path.basename(target_filename.name)}, 'screenshots', cur_2)
        file_obj.save(target_filename.name)

        if len(regression_insert_ids.keys()):
          # update regression_results to set screenshot field
          for reg_ins_id, fname in regression_insert_ids:
            if fname == file_obj.filename:
              cur_2.query('UPDATE regression_results SET screenshot = %s WHERE id = %s' % (insert_id,reg_ins_id))
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
  the_query = ('INSERT INTO %s (`' % table) + '`, `'.join(insert_data.keys()) + '`) VALUES (%('+ (')s, %('.join(insert_data.keys())) + ')s)'
  cur_2.execute(the_query, insert_data)
  return cur_2.lastrowid

# http://stackoverflow.com/questions/6618344/python-mysqldb-and-escaping-table-names ??
def get_existing_domain_id(datastr, insert_if_not_found=True):
  datastr_id = None
  g.cur_1.execute('SELECT id FROM domains WHERE domain LIKE %s',  (datastr,))
  if g.cur_1.rowcount > 0:
    row = g.cur_1.fetchone()
    datastr_id = row['id']
  elif insert_if_not_found:
    g.cur_2.execute('INSERT INTO domains (domain) VALUES (%s)',  (datastr,))
    g.con.commit()
    datastr_id = g.cur_2.lastrowid
  return datastr_id

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

def query_to_object(query, obj, prop, massage_method=None):
  try:
    g.cur_1.execute(query)
  except Exception, e:
    print(e)
  if prop not in obj:
    obj[prop] = []
  for i in range(g.cur_1.rowcount):
    if massage_method:
      obj[prop].append(massage_method(g.cur_1.fetchone()))
    else:
      obj[prop].append(g.cur_1.fetchone())

# Some methods to "massage" data from the database for presentation
def screenshot_url(row):
  url_parts = request.url.split('/')
  # replace the 'topic' with the word 'screenshot'
  url_parts[3] = 'screenshot'
  row['file'] = '%s/%s' % ('/'.join(url_parts),row['file'])
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
  if not tmp.subdomain in ['www', '', 'm']:
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
  elif 'MSIE' in uastr  > -1 or 'Trident' in uastr:
    name = 'IE'
  elif 'Opera' in uastr:
    name = 'Opera'
  elif 'Safari' in uastr:
    name = 'Safari'

  if 'Mobile' in uastr:
    if 'Android' in uastr:
      platform = 'Android'
    else:
      platform =  'OS' if name == 'Firefox' else 'Mobile'
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
    app.run('localhost', port=port)
    print('Serving on port %s' % port)


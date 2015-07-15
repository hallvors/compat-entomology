from flask import Flask, request, g, jsonify, make_response
import tldextract

def get_existing_domain_id(datastr, insert_if_not_found=True):
    datastr_id = None
    g.cur_1.execute('SELECT id FROM domains WHERE domain LIKE ?',  (datastr,))
    all_entries = g.cur_1.fetchall()
    if len(all_entries) == 1:
        row = all_entries[0]
        datastr_id = row['id']
    elif insert_if_not_found:
        g.cur_2.execute(
            'INSERT INTO domains (domain) VALUES (?)',  (datastr,))
        g.con.commit()
        datastr_id = g.cur_2.lastrowid
    return datastr_id

def query_to_object(query, params, obj, prop, massage_method=None):
    try:
        g.cur_1.execute(query, params)
    except Exception, e:
        print(e)
    if prop not in obj:
        obj[prop] = []
    for the_row in g.cur_1:
        if massage_method:
            obj[prop].append(massage_method(the_row))
        else:
            obj[prop].append(the_row)

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
    # For now we don't care about versions. Un-comment if we want to..
    # version
    # v = re.search(r"(Firefox\/|Chrome\/|rv:|Version\/)(\d+)", uastr)
    # if v:
    #    version = v.groups()[1]
    return "%s%s%s" % (name, platform, version)

def normalize_domain(domain):
    tmp = tldextract.extract('http://%s' % domain)
    # we remove "meaningless-ish" prefixes only
    if not tmp.subdomain in ['www', '']:
        tmp = '%s.%s.%s' % (tmp.subdomain, tmp.domain, tmp.suffix)
    else:
        tmp = '%s.%s' % (tmp.domain, tmp.suffix)
    return tmp

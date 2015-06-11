from flask import Flask, request, g, jsonify, make_response


def get_existing_domain_id(datastr, insert_if_not_found=True):
    datastr_id = None
    g.cur_1.execute('SELECT id FROM domains WHERE domain LIKE %s',  (datastr,))
    if g.cur_1.rowcount > 0:
        row = g.cur_1.fetchone()
        datastr_id = row['id']
    elif insert_if_not_found:
        g.cur_2.execute(
            'INSERT INTO domains (domain) VALUES (%s)',  (datastr,))
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


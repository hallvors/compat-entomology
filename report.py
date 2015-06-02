import os
import json
import re
import tldextract
import tempfile
from flask import Flask, request, g, jsonify, make_response
from utils import get_existing_domain_id

import pdb

def generate_site_diff_report(sites, cur_1):
    # Get all UA strings and classify them in Gecko/WebKit
    cur_1.execute('SELECT * FROM uastrings')
    wkuas = []
    gkuas=[]
    for i in range(cur_1.rowcount):
        row = cur_1.fetchone()
        if 'WebKit' in row['ua']:
            wkuas.append(row['id'])
        else:
            gkuas.append(row['id'])
    differences = {}
    no_issues = []
    lacks_data = []
    wkdata = None
    gkdata = None
    for site in sites:
        # Get site id from sites table
        site_id = get_existing_domain_id(site, False)
        if not site_id:
            continue
        # Look up recent test_data results for site (for two
        # different UAs from different browser
        # families)
        #pdb.set_trace()
        cur_1.execute('SELECT * FROM test_data WHERE site = "%s" AND ua IN (%s) ORDER BY id DESC LIMIT 1' % (site_id,json.dumps(gkuas)[1:-1]))
        if cur_1.rowcount == 1:
            gkdata = cur_1.fetchone()
        else:
            lacks_data.append({site: '(Insufficient data, no Gecko results)'})
            continue
        cur_1.execute('SELECT * FROM test_data WHERE site = "%s" AND ua IN (%s) ORDER BY id DESC LIMIT 1' % (site_id,json.dumps(wkuas)[1:-1]))
        if cur_1.rowcount == 1:
            wkdata = cur_1.fetchone()
        else:
            lacks_data.append({site: '(Insufficient data, no WebKit results)'})
            continue
        # Compare test results. Output site and short
        # explanation if different
        for prop in gkdata:
            if gkdata[prop] == None or wkdata[prop] == None:
                continue
            if prop in ['id', 'data_set', 'ua', 'engine', 'other_plugin_data', 'site']:
                continue;
            if gkdata[prop] != wkdata[prop]:
                if site not in differences:
                    differences[site] = []
                differences[site].append('%s is %s for gecko-UA, %s for other UA (%s,%s)' % (prop,gkdata[prop],wkdata[prop],gkdata['id'],wkdata['id']))
        # TODO:
        # Repeat for tables
        #  * redirects
        #  * regression_results
        #  * js_problems
        #  * css_problems
        # although for some of these we have a problem:
        # absence of evidence is not evidence of absence
        if site not in differences:
            no_issues.append(site)

    #differences['no_issues'] = no_issues
    #differences['lacks_data'] = lacks_data
    return differences
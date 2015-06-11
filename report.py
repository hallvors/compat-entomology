import os
import json
import re
import tldextract
import tempfile
from flask import Flask, request, g, jsonify, make_response
from utils import get_existing_domain_id, query_to_object

import pdb

def generate_site_diff_report(sites, cur_1):
    # Get all UA strings and classify them in Gecko/WebKit
    # TODO:get rid of this and use ua_family when DB is updated..
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
    data = {'wkdata':{}, 'gkdata':{}}
    # For some tables, missing data is significant
    log_missing_data_tables = ['js_problems', 'css_problems', 'redirects']
    if wkuas and gkuas:
        for site in sites:
            # Get site id from sites table
            site_id = get_existing_domain_id(site, False)
            if not site_id:
                continue
            # Look up recent test_data results for site (for two
            # different UAs from different browser
            # families)
            for ua_ids in [('wkdata', wkuas), ('gkdata', gkuas)]:
                for table in ['test_data', 'redirects', 'js_problems', 'css_problems']:
                    query_to_object('SELECT * FROM %s WHERE site = "%s" AND ua IN (%s) ORDER BY id DESC LIMIT 1' % (table, site_id, json.dumps(ua_ids[1])[1:-1]), data[ua_ids[0]], table)
                    if not data[ua_ids[0]][table]:
                        lacks_data.append({site: '(Insufficient data for %s, no %s results)' % (table, ua_ids[0])})

            # Compare test results (test_data table). Output site and short
            # explanation if different
            if data['gkdata']['test_data']:
                for prop in data['gkdata']['test_data'][0]:
                    if prop in ['id', 'data_set', 'ua', 'ua_type', 'engine', 'other_plugin_data', 'site']:
                        # skip metadata fields..
                        continue;
                    if data['gkdata']['test_data'][0][prop] == None or data['wkdata']['test_data'][0][prop] == None:
                        # if some data is missing entirely, we assume it's the testing
                        # scripts being inconsistent - probably not interesting
                        continue
                    if data['gkdata']['test_data'][0][prop] != data['wkdata']['test_data'][0][prop]:
                        if site not in differences:
                            differences[site] = {'test_data':[]}
                        differences[site]['test_data'].append('%s is %s for gecko-UA, %s for other UA (rows: %s,%s)' % (prop,data['gkdata']['test_data'][0][prop],data['wkdata']['test_data'][0][prop],data['gkdata']['test_data'][0]['id'],data['wkdata']['test_data'][0]['id']))
            # TODO - can we make any comparisons here at all?
            # For CSS - not sure..
            for table in log_missing_data_tables:
                if data['gkdata'][table]:
                    if site not in differences:
                        differences[site] = {table:{'gecko':data['gkdata'][table]}}
                if data['wkdata'][table]:
                    if site not in differences:
                        differences[site] = {table:{'gecko':data['wkdata'][table]}}


            if site not in differences:
                no_issues.append(site)

        #differences['no_issues'] = no_issues
        #differences['lacks_data'] = lacks_data
    else:
        # Insufficient data: lacks two types of UA strings in UA db..
        pass
    return differences
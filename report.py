import os
import json
import re
import tldextract
import tempfile
from flask import Flask, request, g, jsonify, make_response
from utils import get_existing_domain_id, query_to_object, normalize_domain

import pdb

def generate_site_diff_report_old(sites, cur_1):
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
    # for some tables, we just dump data from last month:
    # TODO: 10 is a very low (and random) limit, but we have a real firehose problem here..
    table_queries = {
        'js_problems': 'SELECT DISTINCT js_problems.message, js_problems.stack, js_problems.ua_type, testdata_sets.date FROM js_problems, testdata_sets WHERE js_problems.site = "%s" AND js_problems.ua IN (%s) AND js_problems.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 1 month) ORDER BY js_problems.id DESC LIMIT 10',
        'css_problems': 'SELECT DISTINCT css_problems.file, css_problems.selector, css_problems.property, css_problems.value, css_problems.ua_type, testdata_sets.date FROM css_problems, testdata_sets WHERE css_problems.site = "%s" AND css_problems.ua IN (%s) AND css_problems.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 1 month) ORDER BY css_problems.id DESC LIMIT 10',
        'redirects': 'SELECT DISTINCT redirects.urls, redirects.final_url, redirects.ua_type, testdata_sets.date FROM redirects, testdata_sets WHERE redirects.site = "%s" AND redirects.ua IN (%s) AND redirects.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 1 month) ORDER BY redirects.id DESC LIMIT 10'
    }
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
                query_to_object('SELECT DISTINCT * FROM test_data WHERE site = "%s" AND ua IN (%s) ORDER BY id DESC LIMIT 1' % (site_id, json.dumps(ua_ids[1])[1:-1]), data[ua_ids[0]], 'test_data')
                for table in ['redirects', 'js_problems']:
                    query_to_object(table_queries[table] % (site_id, json.dumps(ua_ids[1])[1:-1]), data[ua_ids[0]], table)

                    if not data[ua_ids[0]][table]:
                        lacks_data.append({site: '(Insufficient data for %s, no %s results)' % (table, ua_ids[0])})
            # Compare test results (test_data table). Output site and short
            # explanation if different
            if data['gkdata']['test_data'] and data['wkdata']['test_data']:
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
                        differences[site]['test_data'].append({prop:{'gecko':data['gkdata']['test_data'][0][prop], 'ua_type_g':data['gkdata']['test_data'][0]['ua_type'],'webkit':data['wkdata']['test_data'][0][prop], 'ua_type_wk':data['wkdata']['test_data'][0]['ua_type']}})
            # TODO - can we make any comparisons here at all?
            # For CSS - not sure..
            for table in log_missing_data_tables:
                if table in data['gkdata'] and data['gkdata'][table]:
                    if site not in differences:
                        differences[site] = {table:{'gecko-ua':data['gkdata'][table]}}
                if table in data['wkdata'] and data['wkdata'][table]:
                    if site not in differences:
                        differences[site] = {table:{'webkit-ua':data['wkdata'][table]}}


            if site not in differences:
                no_issues.append(site)

        differences['no_issues'] = no_issues
        #differences['lacks_data'] = lacks_data
    else:
        differences['message'] = 'Insufficient data: lacks two types of UA strings in UA db..'
        pass
    return differences


def generate_site_diff_report(sites, cur_1):
    # Output data for generating a "matrix" of results?
    output = {}
    site_ids = []
    ignore_fields = ['id', 'data_set', 'ua', 'ua_type', 'engine', 'other_plugin_data', 'site', 'failing_because']
    for site in sites:
        # Get site id from sites table
        site = normalize_domain(site)
        site_id = get_existing_domain_id(site, False)
        if not site_id:
            continue
        site_ids.append({'domain':site, 'id':site_id})
        output[site] = {}
    ua_types = []
    # Create a list of UA types we have test results for this site from during the last three months
    # maybe we can optimize this?
    cur_1.execute('SELECT DISTINCT test_data.ua_type FROM test_data, testdata_sets WHERE test_data.site IN (%s) AND test_data.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 3 month)' % ', '.join([str(item['id']) for item in site_ids]))
    for i in range(cur_1.rowcount):
        the_type = cur_1.fetchone()
        if the_type:
            ua_types.append(the_type['ua_type'])

    if not ua_types:
        # wot, we have no data at all??
        return

    for this_site in site_ids:
        tmp_results = {}
        for ua_type in ua_types:
            print("%s %s" % (this_site['domain'],ua_type))
            query_to_object('SELECT DISTINCT * FROM test_data WHERE site = "%s" AND ua_type LIKE "%s" ORDER BY id DESC LIMIT 1' % (this_site['id'], ua_type), tmp_results, ua_type)
            # we want to have redirects available for comparison too..
            cur_1.execute('SELECT DISTINCT redirects.urls, redirects.final_url, redirects.ua_type, testdata_sets.date FROM redirects, testdata_sets WHERE redirects.site = "%s" AND redirects.ua_type LIKE "%s" AND redirects.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 3 month) ORDER BY redirects.id DESC LIMIT 1' % (this_site['id'],ua_type))
            if cur_1.rowcount == 1:
                if not tmp_results[ua_type]:
                    tmp_results[ua_type] = [{}]
                tmp_results[ua_type][0]['redirect_urls'] = cur_1.fetchone()['urls']

            if not tmp_results[ua_type]:
                # there was no data.. Forget about this ua type to avoid problems in iteration below.
                del tmp_results[ua_type]
        # We don't care about data whose value across three UAs is same
        # we now have the last test data for $site sorted by ua_type.
        # tmp_results[ua_type][0]['hasViewportMeta']
        if not tmp_results:
            # ops, no data at all about this site - move on
            continue
        print(tmp_results)
        # Sure, this gets a bit complex: we want to iterate over keys (ua_type like FirefoxAndroid)
        # but we don't know which keys are available for each site..
        # Anyway, we take the first ua type (tmp_results.keys()[0]), get the first db row of results
        # for that ua type(tmp_results[first_ua][0]) and enumerates the key/values of its properties (items()).
        these_ua_types = tmp_results.keys()
        if not these_ua_types:
            continue
        if len(these_ua_types) == 1:
            # only data for one single UA, no diff'ing possible
            continue
        first_ua = these_ua_types[0]
        print(first_ua)
        for prop, first_value in tmp_results[first_ua][0].items():
            if prop in ignore_fields:
                continue
            # Now we compare this first value against the values for other UA types (starting range
            # from 1 since we already have the value for the 0th ua type)
            for i in range(1, len(these_ua_types)):
                print("i: %s" % i)
                print(these_ua_types[i])
                if not tmp_results[these_ua_types[i]]:
                    # No data for this UA type on this site (we should never end up here, but whatever..)
                    continue
                if not prop in tmp_results[these_ua_types[i]][0]:
                    # some missing data.. move on to next UA, please..
                    continue

                print("%s %s - comparing %s and %s" %(prop, i, first_value, tmp_results[these_ua_types[i]][0][prop]))
                if first_value != tmp_results[these_ua_types[i]][0][prop]:
                    # property value differs between UAs, let's record this.
                    # But first a null check - None means test did not run, and is probably an issue
                    # with the test framework rather than with the site
                    if first_value == None or tmp_results[these_ua_types[i]][0][prop] == None:
                        continue
                    details = {first_ua: first_value}
                    # we will record all other values we have
                    for ua_type in these_ua_types[1:]:
                        if ua_type in tmp_results and tmp_results[ua_type] and prop in tmp_results[ua_type][0]:
                            details[ua_type] = tmp_results[ua_type][0][prop]
                    output[this_site['domain']][prop] = details
        print(this_site)
        print('DONE')
    return output


    table_queries = {
        'js_problems': 'SELECT DISTINCT js_problems.message, js_problems.stack, js_problems.ua_type, testdata_sets.date FROM js_problems, testdata_sets WHERE js_problems.site = "%s" AND js_problems.ua IN (%s) AND js_problems.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 1 month) ORDER BY js_problems.id DESC LIMIT 10',
        'css_problems': 'SELECT DISTINCT css_problems.file, css_problems.selector, css_problems.property, css_problems.value, css_problems.ua_type, testdata_sets.date FROM css_problems, testdata_sets WHERE css_problems.site = "%s" AND css_problems.ua IN (%s) AND css_problems.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 1 month) ORDER BY css_problems.id DESC LIMIT 10',
        'redirects': 'SELECT DISTINCT redirects.urls, redirects.final_url, redirects.ua_type, testdata_sets.date FROM redirects, testdata_sets WHERE redirects.site = "%s" AND redirects.ua IN (%s) AND redirects.data_set = testdata_sets.id AND testdata_sets.date > date_sub(now(), interval 1 month) ORDER BY redirects.id DESC LIMIT 10'
    }


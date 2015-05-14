import MySQLdb as mdb
import pprint, pdb, time, glob, os, re, json, sys
from dbconf import database_connect

con, cur_1, cur_2 = database_connect()

table_queries = [
    # comment out these first queries if you don't want a full DB reset..
    'DROP TABLE IF EXISTS domains',
    'DROP TABLE IF EXISTS uastrings',
    'DROP TABLE IF EXISTS comments',
    'DROP TABLE IF EXISTS test_data',
    'DROP TABLE IF EXISTS contacts',
    'DROP TABLE IF EXISTS screenshots',
    'DROP TABLE IF EXISTS css_problems',
    'DROP TABLE IF EXISTS js_problems',
    'DROP TABLE IF EXISTS regression_results',
    'DROP TABLE IF EXISTS redirects',
    'DROP TABLE IF EXISTS testdata_sets',
    # set up the 'domains' table - our master list of sites.
    'CREATE TABLE IF NOT EXISTS domains (id INT AUTO_INCREMENT, domain VARCHAR(253) CHARACTER SET utf8 COLLATE utf8_bin, PRIMARY KEY(id), UNIQUE(domain))',
    # set up helper table: UA strings
    'CREATE TABLE IF NOT EXISTS uastrings (id INT AUTO_INCREMENT, ua TEXT CHARACTER SET utf8 COLLATE utf8_bin, human_desc TINYTEXT, PRIMARY KEY(id))',
    # set up table for human review results
    # TODO: hook into GitHub to be able to associate submitted comments with GitHub user name..?
    'CREATE TABLE IF NOT EXISTS comments (id INT AUTO_INCREMENT, site INT, date TIMESTAMP, handled TINYINT(1) DEFAULT 0, type ENUM("screenshot", "testing", "thumbsupdown"), comment TEXT, screenshot INT, github_nick TINYTEXT, PRIMARY KEY(id))',
    # regression tests - table for results
    # these can be submitted from slimerjstester.js for example
    # they might include screenshot(s) (if so the screenshot value
    # here will refer to an insert_id in the screenshots table)
    'CREATE TABLE IF NOT EXISTS regression_results (id INT AUTO_INCREMENT, site INT, ua INT, engine TINYTEXT, date TIMESTAMP, bug_id TINYTEXT, result TEXT, screenshot INT, PRIMARY KEY(id))',
    # test data table
    # TO EVALUATE: is it better to add fields for each plugin? Yes, with the drawback that adding plugins becomes harder..
    # perhaps a mixed solution where every key-value that has a key in the table is inserted, rest is JSON stringified
    # and added to plugin_data.
    'CREATE TABLE IF NOT EXISTS test_data (id INT AUTO_INCREMENT, data_set INT, site INT, ua INT, engine TINYTEXT, state TINYINT(1), failing_because TEXT, hasHandheldFriendlyMeta TINYINT(1), hasViewportMeta TINYINT(1), hasMobileOptimizedMeta TINYINT(1), mobileLinkOrScriptUrl TINYINT(1), hasVideoTags TINYINT(1), pageWidthFitsScreen TINYINT(1), hasHtmlOrBodyMobileClass TINYINT(1), `iscroll` TINYINT(1), `link-prerender` TINYINT(1), `m3u8-links` TINYINT(1), `m3u8-videos` TINYINT(1), `mobify-check` TINYINT(1), `modernizr-at-media` TINYINT(1), `old-brightcove` TINYINT(1), `sencha-touch` TINYINT(1), `window-orientation-usage` TINYINT(1), `wptouch-check` TINYINT(1), other_plugin_data TEXT, PRIMARY KEY(id))',
    # a table of contact points - filled through automated discovery of contact forms,
    # social media accounts etc
    # Note: this is for "public" data only - not intended for dev E-mail addresses found on GitHub or LinkedIN..
    'CREATE TABLE IF NOT EXISTS contacts (id INT AUTO_INCREMENT, site INT, form TINYTEXT, form_source TINYTEXT, email TINYTEXT, email_source TINYTEXT, twitter TINYTEXT, twitter_source TINYTEXT, facebook TINYTEXT, facebook_source TINYTEXT, linkedin TINYTEXT, linkedin_source TINYTEXT, gplus TINYTEXT, gplus_source TINYTEXT, PRIMARY KEY(id))',
    # a table of screenshots..
    'CREATE TABLE IF NOT EXISTS screenshots (id INT AUTO_INCREMENT, data_set INT, ua INT, engine TINYTEXT, file TINYTEXT, PRIMARY KEY(id))',
    # a table for CSS problems..
    'CREATE TABLE IF NOT EXISTS css_problems (id INT AUTO_INCREMENT, data_set INT, ua INT, engine TINYTEXT, file TEXT, selector TINYTEXT, property TINYTEXT, value TINYTEXT, PRIMARY KEY(id))',
    # a table for JS problems..
    'CREATE TABLE IF NOT EXISTS js_problems (id INT AUTO_INCREMENT, data_set INT, ua INT, engine TINYTEXT, stack TEXT, message TINYTEXT, PRIMARY KEY(id))',
    # a table for redirects..
    'CREATE TABLE IF NOT EXISTS redirects (id INT AUTO_INCREMENT, data_set INT, ua INT, engine TINYTEXT, urls TEXT, PRIMARY KEY(id))',
    # a meta table for testdata sets, helps track data that belongs together..
    'CREATE TABLE IF NOT EXISTS testdata_sets (id INT AUTO_INCREMENT, site INT, url TEXT, date TIMESTAMP, PRIMARY KEY(id))'
];

for query in table_queries:
    cur_1.execute(query)

dbdesc = {}
tables = []
cur_1.execute('SHOW TABLES')
for row in cur_1.fetchall():
    tables.append(row.values()[0])
for table in tables:
    #print(table)
    dbdesc[table] = []
    cur_1.execute('DESC %s' % table)
    for row in cur_1.fetchall():
        dbdesc[table].append(row['Field'])

f = open('dbdesc.json', 'w')
f.write(json.dumps(dbdesc, indent=2))
f.close()

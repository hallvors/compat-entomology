import os
import urlparse
import sqlite3 as sqlite

if os.path.exists('/files/'):
    # On the PaaS server, /files/ is a link to a file service
    # Make sure the database file is there to ensure it survives updates
    DB_FILE = '/files/compat_entomology.db'
else:
    # Otherwise, to simplify local testing we create the DB file in a 'files'
    # sub-folder - if the user didn't already create it, we do now
    if not os.path.exists('./files/'):
        os.path.mkdir('./files/')
    DB_FILE = './files/compat_entomology.db'

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def database_connect():
    con = sqlite.connect(DB_FILE)
    # con.row_factory = sqlite.Row # not JSON serializable..
    con.row_factory = dict_factory
    cur_1 = con.cursor()
    cur_2 = con.cursor()
    return con, cur_1, cur_2

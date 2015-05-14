import urlparse, os
import MySQLdb as mdb

def database_connect():
    if 'DATABASE_URL' in os.environ:
        url = urlparse.urlparse(os.environ['DATABASE_URL'])
        #print(url)
        con = mdb.connect(url.hostname, url.username, url.password, url.path[1:], charset='utf8')
    else:
        quit('needs DB connection..')

    cur_1 = con.cursor(mdb.cursors.DictCursor)
    cur_2 = con.cursor(mdb.cursors.DictCursor)

    return con, cur_1, cur_2
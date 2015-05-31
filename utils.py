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

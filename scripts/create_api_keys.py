import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='daiict_db', user='postgres', password='root')
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS api_keys (
    email       VARCHAR(255) PRIMARY KEY,
    hashed_key  VARCHAR(255) NOT NULL,
    role        VARCHAR(50)  DEFAULT 'User',
    created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    last_used   TIMESTAMP,
    status      VARCHAR(20)  DEFAULT 'Active'
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hashed ON api_keys (hashed_key)")
cur.close()
conn.close()
print("Done: api_keys table created successfully.")

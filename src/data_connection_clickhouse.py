import clickhouse_connect
import yaml

def create_clickhouse_client(config: dict):
    return clickhouse_connect.get_client(**config)


def query_clickhouse(client, sql: str):
    return client.query_df(sql)

if __name__ == "__main__":

    # 数据库连接
    client = create_clickhouse_client({
        "host": "10.8.214.68",
        "port":8123,
        "user":"TEC_KAFKA_READ",
        "password":"Password@123456",
        "database":"KAFKA",
        "secure": False}
        )  

    # 测试连接
    print("ClickHouse connected successfully!")
    print("Server version:", client.server_version)

    # SQL 查询
    sql = "SELECT * FROM KAFKA.MECN_MOE6_RUNTIMEPARAMMONITOR_WEBSCADA_JSON_PROCESSED_V02 LIMIT 1000"


    # 直接转换成 DataFrame
    df = query_clickhouse(client, sql)

    print(df.head())
    print(df.shape)
    print(df.dtypes)

    # 关闭连接
    client.close()


    

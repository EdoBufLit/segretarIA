import os
from redis import Redis
from rq import Worker, Queue
from queue_utils import get_redis_connection
from dotenv import load_dotenv

load_dotenv()

listen = ['default']

def run_worker():
    conn = get_redis_connection()
    # Explicitly pass connection to Worker
    queues = [Queue(name, connection=conn) for name in listen]
    worker = Worker(queues, connection=conn)
    worker.work()

if __name__ == '__main__':
    run_worker()

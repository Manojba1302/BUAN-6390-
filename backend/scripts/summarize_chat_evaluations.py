"""Metadata-only daily report. Run: python -m scripts.summarize_chat_evaluations --date YYYY-MM-DD."""
import argparse
from collections import Counter
from datetime import date
import json
import math
from statistics import median
from app.agent.evaluation_store import _client
from app.core.config import settings


def records(day):
    client = _client()
    prefix = "chat/date="+date.fromisoformat(day).isoformat()+"/"
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=settings.chat_evaluation_bucket,Prefix=prefix):
        for item in page.get("Contents",[]):
            body = client.get_object(Bucket=settings.chat_evaluation_bucket,Key=item["Key"])["Body"].read()
            yield json.loads(body)


def report(items):
    result = {"requests":len(items),"routes":dict(Counter(i["route"] for i in items)),"outcomes":dict(Counter(i["outcome"] for i in items)),"latency":{}}
    for stage in ("total_seconds","embedding_seconds","retrieval_seconds","first_token_seconds","generation_seconds"):
        values = sorted(i["timings"][stage] for i in items if i["timings"].get(stage) is not None)
        if values:
            result["latency"][stage] = {"samples":len(values),"p50":median(values),"p95":values[math.ceil(.95*len(values))-1]}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",required=True)
    args = parser.parse_args()
    print(json.dumps(report(list(records(args.date))),indent=2))

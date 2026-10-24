import json
import os
import secrets
import string
import boto3
from urllib.parse import urlparse

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("url-shortener-links")

ALPHABET = string.ascii_letters + string.digits


def is_valid_url(url):
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and not any(c.isspace() for c in url)
        )
    except (ValueError, TypeError):
        return False


def generate_short_code(length=6):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def response(status_code, body, headers=None):
    return {
        "statusCode": status_code,
        "headers": headers or {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body)
    }


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get(
        "http", {}
    ).get("method", "")

    path = event.get("rawPath", "")

    # POST /shorten
    if method == "POST" and path.endswith("/shorten"):
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return response(400, {"error": "Invalid JSON body."})

        url = body.get("url")

        if not isinstance(url, str) or not is_valid_url(url):
            return response(
                400,
                {"error": "Please provide a valid HTTP or HTTPS URL."}
            )

        # Retry if a randomly generated code already exists.
        for _ in range(5):
            short_code = generate_short_code()
            try:
                table.put_item(
                    Item={
                        "short_code": short_code,
                        "original_url": url
                    },
                    ConditionExpression="attribute_not_exists(short_code)"
                )
                return response(201, {
                    "short_code": short_code,
                    "short_url": (
                        f"{event.get('headers', {}).get('x-forwarded-proto', 'https')}://"
                        f"{event.get('headers', {}).get('host', '')}"
                        f"/r/{short_code}"
                    ),
                    "original_url": url
                })
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                continue

        return response(500, {"error": "Could not generate a unique code."})

    # GET /r/{short_code}
    if method == "GET" and "/r/" in path:
        short_code = path.rsplit("/r/", 1)[-1]
        print("GET path:", path)
        print("GET short_code:", repr(short_code))

        if not short_code:
            return response(400, {"error": "Missing short code."})

        result = table.get_item(Key={"short_code": short_code})

        print("TABLE:", table.name)
        print("LOOKUP CODE:", repr(short_code))
        print("DYNAMODB RESULT:", json.dumps(result, default=str))

        item = result.get("Item")

        if not item:
            return response(404, {"error": "Short URL not found."})

        return {
            "statusCode": 302,
            "headers": {
                "Location": item["original_url"]
            },
            "body": ""
        }

    return response(404, {"error": "Route not found."})

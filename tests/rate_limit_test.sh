#!/bin/bash

BASE_URL="http://127.0.0.1:8000"

echo "Testing Rate Limit on /login (POST)"
echo "-----------------------------------"

for i in {1..10}; do
    response=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE_URL/login -d "username=test&password=test")
    echo "Request $i: HTTP $response"
done

echo ""
echo "Testing Rate Limit on /admin/clients (GET)"
echo "------------------------------------------"
# Note: This might return 401/403 or Redirect (302) if auth is checked first.
# Rate limit should ideally trigger even for unauth if it's IP based and high volume?
# Or maybe only for login endpoints? The spec says "Verify /admin/* rate-limited too".

for i in {1..10}; do
    response=$(curl -s -o /dev/null -w "%{http_code}" $BASE_URL/admin/clients)
    echo "Request $i: HTTP $response"
done

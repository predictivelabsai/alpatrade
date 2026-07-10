#!/bin/bash
# Combinatorial API test runner
# Reads test-data/api_endpoints.csv and calls each endpoint against the live API.
# Results written to test-results/api-results.json

API_BASE="${API_BASE_URL:-https://carhero.chat/api/v1}"
RESULTS_FILE="test-results/api-results.json"
mkdir -p test-results

echo "Testing API at: $API_BASE"
echo '{"test_run": "'$(date -Iseconds)'", "api_base": "'$API_BASE'", "results": [' > "$RESULTS_FILE"

FIRST=true
PASS=0
FAIL=0
TOTAL=0

# Skip header line
tail -n +2 test-data/api_endpoints.csv | while IFS=',' read -r id method path auth_required expected_status description; do
  TOTAL=$((TOTAL + 1))

  # Build curl command
  URL="${API_BASE}${path}"
  CURL_OPTS="-s -o /tmp/api_test_body.txt -w %{http_code} --max-time 30"

  if [ "$method" = "POST" ]; then
    if echo "$path" | grep -q "contact" && [ "$expected_status" = "200" ]; then
      BODY='{"name":"Test","email":"test@test.com","message":"Test message"}'
    elif echo "$path" | grep -q "contact" && [ "$expected_status" != "200" ]; then
      BODY='{}'
    elif echo "$path" | grep -q "auth/login"; then
      BODY='{"email":"wrong@test.com","password":"wrong"}'
    elif echo "$path" | grep -q "auth/register"; then
      BODY='{}'
    elif echo "$path" | grep -q "analytics"; then
      BODY='{"question":"count of listings"}'
    elif echo "$path" | grep -q "favorites"; then
      BODY='{"listing_id":1}'
    else
      BODY='{}'
    fi
    STATUS=$(curl $CURL_OPTS -X POST -H "Content-Type: application/json" -d "$BODY" "$URL" 2>/dev/null)
  elif [ "$method" = "DELETE" ]; then
    STATUS=$(curl $CURL_OPTS -X DELETE "$URL" 2>/dev/null)
  else
    STATUS=$(curl $CURL_OPTS "$URL" 2>/dev/null)
  fi

  RESPONSE_BODY=$(cat /tmp/api_test_body.txt 2>/dev/null | head -c 500)

  # Check if status matches expected (handle 401/403 as equivalent for auth-required)
  if [ "$expected_status" = "401" ] && ([ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]); then
    RESULT="pass"
  elif [ "$STATUS" = "$expected_status" ]; then
    RESULT="pass"
  elif [ "$expected_status" = "422" ] && [ "$STATUS" = "422" ]; then
    RESULT="pass"
  else
    RESULT="fail"
  fi

  # Escape JSON strings
  DESC_ESCAPED=$(echo "$description" | sed 's/"/\\"/g')
  BODY_ESCAPED=$(echo "$RESPONSE_BODY" | tr '\n' ' ' | sed 's/"/\\"/g' | head -c 200)

  if [ "$FIRST" = true ]; then
    FIRST=false
  else
    echo ',' >> "$RESULTS_FILE"
  fi

  echo -n '  {"id": '$id', "method": "'$method'", "path": "'$path'", "expected": '$expected_status', "actual": '$STATUS', "result": "'$RESULT'", "description": "'"$DESC_ESCAPED"'", "response_preview": "'"$BODY_ESCAPED"'"}' >> "$RESULTS_FILE"

  if [ "$RESULT" = "pass" ]; then
    echo "  ✓ #$id $method $path -> $STATUS (expected $expected_status)"
  else
    echo "  ✗ #$id $method $path -> $STATUS (expected $expected_status) FAIL"
  fi
done

echo '' >> "$RESULTS_FILE"
echo ']}' >> "$RESULTS_FILE"

echo ""
echo "Results written to $RESULTS_FILE"

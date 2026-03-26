# Aliens Eye - Improvements & Enhancements

## Critical Issues

### 1. **AI Scoring Logic Bug**
- **Issue**: `abs_score = abs(score)` uses absolute value, causing inverted confidence
  - A score of -20 ("Not Found") shows 95% confidence
  - User misinterprets confidence as certainty the account exists
- **Impact**: High false negatives/positives
- **Fix**: Remove `abs()` - confidence should reflect score magnitude directly

### 2. **Threshold Too Low**
- **Issue**: Status = "Found" when `score > 3` (extremely lenient)
- **Impact**: 2 positive keywords = profile found, even with error keywords present
- **Fix**: Adjust thresholds (e.g., Found: > 8, Not Found: < -5, Maybe: in between)

### 3. **Keyword Lists Too Generic**
- **Issue**: Error keywords like "error", "sorry", "oops" appear on many pages
- **Impact**: Large number of false positives
- **Fix**: Use more specific error patterns, context-aware matching

## High Priority

### 4. **Pattern Cache Not Persistent**
- **Issue**: Cache resets on every program run
- **Impact**: No learning across sessions, wasted computation
- **Fix**: Save cache to JSON after each scan, load on startup

### 5. **Hardcoded Configuration Values**
- **Issue**: Confidence thresholds (95, 85, 70, 50), scoring weights (-10, -3, +5) hardcoded
- **Impact**: Hard to tune AI behavior, difficult to maintain
- **Fix**: Move to `config.json`:
  ```json
  {
    "confidence_thresholds": {"high": 85, "medium": 70, "low": 50},
    "scoring_weights": {
      "error_keyword": -2,
      "positive_keyword": 1.5,
      "http_200": 5,
      "http_404": -10
    }
  }
  ```

### 6. **Semaphore Limit Hardcoded to 50**
- **Issue**: No way to change concurrent connection limit centrally
- **Impact**: Poor for slow connections, wasteful for fast ones
- **Fix**: Make configurable via CLI with better default detection

### 7. **Logging Underutilized**
- **Issue**: Logger created but barely used; no scan progress logging
- **Impact**: Users can't track long-running scans or debug issues
- **Fix**: Add logging at key points:
  - Scan start/end per username
  - Per-site start/end (verbose only)
  - AI scoring details (verbose only)

## Medium Priority

### 8. **Code Organization**
- **Issue**: Single 800+ line file, mixed concerns
- **Impact**: Hard to maintain, test, extend
- **Fix**: Split into modules:
  - `scanner.py` - AIUsernameScanner class
  - `detector.py` - AI detection logic
  - `results.py` - Result handling/storage
  - `config.py` - Configuration loading

### 9. **Error Handling Too Generic**
- **Issue**: `except Exception as e:` catches everything; no retry logic
- **Impact**: Network timeouts = immediate fail, no recovery
- **Fix**: Handle specific exceptions:
  ```python
  except asyncio.TimeoutError: # retry with backoff
  except aiohttp.ClientError: # connection issue
  except Exception: # log unexpected
  ```

### 10. **Regex Patterns Duplicated**
- **Issue**: Similar patterns in `extract_dom_structure()` and `_update_pattern_cache()`
- **Impact**: Maintenance nightmare, inconsistent matching
- **Fix**: Define pattern constants, reuse them

### 11. **User-Agent Static**
- **Issue**: Same User-Agent every scan; easily detectable/blockable
- **Impact**: Sites can easily identify and block scanner
- **Fix**: Rotate through realistic user agents from list

### 12. **No Rate Limiting/Backoff**
- **Issue**: Hammers sites with concurrent requests, no 429 handling
- **Impact**: Can get IP banned
- **Fix**: 
  - Add delay between requests per domain
  - Detect 429 responses, exponential backoff
  - Respect Retry-After headers

## Low Priority / Nice-to-Have

### 13. **Feature: Batch Export**
- Add CSV export for multiple results
- Generate summary reports

### 14. **Feature: Result Filtering**
- Filter saved results by confidence/status without rescanning
- Search results by site name

### 15. **Feature: Username Validation**
- Check for invalid characters before scanning
- Suggest corrections (e.g., spaces → underscores)

### 16. **Feature: Proxy Support**
- Route requests through proxy list
- Useful for stealth/bypass

### 17. **Feature: robots.txt Compliance**
- Check robots.txt before scanning
- Optional flag to ignore

### 18. **Code**: Optimize Response Handling
- Check headers before reading full response body
- Skip text parsing for error pages

### 19. **Code**: ASCII Art to File
- Move banner to separate file or load from data
- Reduces main script size

### 20. **Docs**: Add Examples**
- Document expected output
- Show confidence calibration examples
- Add troubleshooting guide

## Summary of Quick Wins (1-2 hours)
1. Fix `abs_score` bug
2. Adjust confidence thresholds
3. Create `config.json` with scoring weights
4. Add basic logging
5. Make semaphore limit CLI configurable

## Summary of Medium Effort (4-6 hours)
1. Modularize code into separate files
2. Improve error handling with retries
3. Add pattern cache persistence
4. Refine keyword lists with context
5. Rotate user agents

## Summary of Large Effort (8+ hours)
1. Implement proper backoff/rate limiting
2. Add comprehensive test suite
3. Support proxies + robots.txt
4. Build web UI or dashboard
5. Full documentation overhaul

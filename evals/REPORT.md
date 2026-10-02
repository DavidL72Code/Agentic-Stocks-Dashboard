# Eval report

Run 2026-10-02 01:29 · model `gemini-3.5-flash-lite` · 41 tools · LLM on

**153/153 passed**


## Auth — 34/34

| Case | Result | Detail |
|---|---|---|
| `hash_not_plaintext` | PASS | $argon2id$v=19$m=65536,t=3,p... |
| `hash_salted` | PASS | two hashes of one password differ |
| `hash_memory_hard` | PASS | argon2id |
| `verify_roundtrip` | PASS | accepts the right one, rejects the wrong one |
| `verify_survives_garbage` | PASS | returns False instead of raising |
| `rejects_weak_passwords` | PASS | rejected all of ['short', 'password123', '9081726354'] |
| `register_rejects_weak` | PASS | 400 Use at least 10 characters. |
| `register_rejects_bad_username` | PASS | 400 Usernames are 3-32 characters: letters, digits, . _ or -, starting with a letter or digit. |
| `register_succeeds` | PASS | 200 probe-8040650b |
| `register_returns_no_password` | PASS | response carries no password field |
| `username_case_insensitive_unique` | PASS | 409 That username is taken. |
| `session_cookie_works` | PASS | probe-8040650b can_save=True |
| `no_user_enumeration` | PASS | real user: 401 / unknown: 401, same text: True |
| `throttle_locks_out` | PASS | 25 failures -> locked for 899s (limit 5) |
| `ip_budget_is_looser` | PASS | 5 fails -> 0s, 50 -> 899s |
| `throttle_clears_on_success` | PASS | cleared |
| `guest_cannot_write` | PASS | 401 Sign in to keep a watchlist or portfolio. |
| `guest_sees_empty_book` | PASS | 200 [] |
| `guest_keeps_market_data` | PASS | 200 1 quote(s) |
| `register_does_not_adopt` | PASS | fresh account sees ['Brokerage'] |
| `seeded_ids_are_per_user` | PASS | ids ['e532de7217d4'] |
| `claim_requires_sign_in` | PASS | 401 Sign in first. |
| `change_needs_current_password` | PASS | 401 Your current password is not right. |
| `change_enforces_strength` | PASS | 400 Use at least 10 characters. |
| `change_succeeds` | PASS | 200 {'ok': True, 'other_sessions_revoked': 0} |
| `change_rotates_the_secret` | PASS | old password 401, new password 200 |
| `delete_needs_confirmation` | PASS | 400 |
| `delete_removes_account` | PASS | delete 204, login after 401 |
| `claim_probe_ran` | PASS | subprocess on a temp database |
| `claim_offered_when_book_exists` | PASS | offered=True, fresh book ['Brokerage'] |
| `claim_moves_the_book` | PASS | 200 -> [['Brokerage', 3], ['Roth IRA', 1]] |
| `claim_survives_name_collision` | PASS | [['Brokerage', 3], ['Roth IRA', 1]] |
| `claim_merges_watchlist` | PASS | ['TSM', 'NVDA', 'AAPL', 'MSFT', 'AMD', 'PLTR', 'KO'] |
| `claim_is_once_only` | PASS | still offered=None, second claim 409 |


## Sign-in — 34/34

| Case | Result | Detail |
|---|---|---|
| `register_200` | PASS | {'id': 'fdf2058a9d6a', 'username': 'davidle', 'name': 'David', 'signed |
| `cookie_httponly` | PASS |  |
| `cookie_samesite_lax` | PASS |  |
| `cookie_persists` | PASS |  |
| `me_knows_user` | PASS | David |
| `can_save` | PASS |  |
| `watchlist_write` | PASS | {'watchlist': ['NVDA', 'AAPL', 'MSFT', 'AMD', 'PLTR', 'KO',  |
| `watchlist_read_back` | PASS |  |
| `portfolio_create` | PASS | {'accounts': [{'id': '4a31ad3d3840', 'name': 'Brokerage', 'k |
| `logout_204` | PASS |  |
| `logout_returns_to_guest` | PASS |  |
| `guest_cannot_write` | PASS |  |
| `guest_sees_nothing` | PASS |  |
| `login_200` | PASS | {'id': 'fdf2058a9d6a', 'username': 'davidle', 'name': 'David |
| `state_survived_logout` | PASS |  |
| `accounts_survived_logout` | PASS |  |
| `username_case_insensitive` | PASS |  |
| `password_case_sensitive` | PASS |  |
| `username_trimmed` | PASS |  |
| `change_200` | PASS | {'ok': True, 'other_sessions_revoked': 2} |
| `old_password_dead` | PASS |  |
| `new_password_works` | PASS |  |
| `changer_stays_signed_in` | PASS |  |
| `other_sessions_revoked` | PASS | 2 revoked |
| `revoked_session_is_dead` | PASS |  |
| `locks_after_max_fails` | PASS | [401, 401, 401, 401, 401, 429] |
| `lockout_beats_correct_password` | PASS |  |
| `lockout_shared_across_processes` | PASS | 899s left in a separate process |
| `reserved_guest` | PASS |  |
| `reserved_admin` | PASS |  |
| `reserved_monsoon` | PASS |  |
| `signup_budget_per_ip` | PASS | 9 created, first 429 at #10 |
| `expired_session_rejected` | PASS |  |
| `expired_sessions_pruned` | PASS | 0 expired rows left |


## Data plane — 15/15

| Case | Result | Detail |
|---|---|---|
| `quotes_batched` | PASS | 8 quotes in 1 upstream request(s) |
| `bars_shape` | PASS | 21 bars, OHLCV shape True |
| `edgar_single_quarter` | PASS | 8 quarters, all single-quarter: True |
| `financials_outlook` | PASS | next 2026-11-17, eps est 2.47332, 8 past reports |
| `overview/NVDA` | PASS | market_cap=5574576046080 |
| `news/NVDA` | PASS | items=[{'title': 'Amazon seeks to offload $8 bln of Nvidia chips t |
| `analysts/NVDA` | PASS | distribution=[{'label': 'Strong buy', 'n': 10}, {'label': 'Buy', 'n': 48} |
| `events/NVDA` | PASS | surprise_history=[{'date': '2026-08-26', 'estimate': 2.09, 'actual': 2.22, 's |
| `indices` | PASS | indices=[{'symbol': '^GSPC', 'label': 'S&P 500', 'level': 7666.45, ' |
| `compare` | PASS | correlations=[{'pair': 'AMD/AVGO', 'corr': 0.53}, {'pair': 'NVDA/AMD', 'c |
| `related/NVDA` | PASS | read_across={'ticker': 'NVDA', 'peers': [{'peer': 'AMD', 'peer_name': 'A |
| `portfolio/analytics` | PASS | concentration={'weights_pct': [{'ticker': 'NVDA', 'pct': 47.5}, {'ticker': |
| `search` | PASS | results=[{'symbol': 'KO', 'name': 'Coca-Cola Company (The)', 'type': |
| `fear_greed` | PASS | score 28.0 (fear) |
| `indices_set` | PASS | ['S&P 500', 'Dow Jones', 'Nasdaq', 'Fear & Greed', 'Volatility', 'US 10-year'] |


## Tools — 51/51

| Case | Result | Detail |
|---|---|---|
| `tool:next_earnings` | PASS | data (events) |
| `tool:earnings_surprise_history` | PASS | data (events) |
| `tool:recent_filings` | PASS | data (events) |
| `tool:ex_dividend` | PASS | data (events) |
| `tool:income_statement` | PASS | data (fundamentals) |
| `tool:valuation_multiples` | PASS | data (fundamentals) |
| `tool:profitability` | PASS | data (fundamentals) |
| `tool:growth_rates` | PASS | data (fundamentals, derived) |
| `tool:leverage_liquidity` | PASS | data (fundamentals) |
| `tool:dividend_economics` | PASS | data (fundamentals) |
| `tool:share_count` | PASS | data (fundamentals) |
| `tool:market_news` | PASS | data (macro) |
| `tool:index_levels` | PASS | data (macro) |
| `tool:sector_news` | PASS | data (macro) |
| `tool:quote` | PASS | data (market) |
| `tool:price_series` | PASS | data (market) |
| `tool:range_52w` | PASS | data (market) |
| `tool:moving_averages` | PASS | data (market, derived) |
| `tool:rsi_momentum` | PASS | data (market, derived) |
| `tool:volatility` | PASS | data (market, derived) |
| `tool:volume_profile` | PASS | data (market, derived) |
| `tool:drawdown` | PASS | data (market, derived) |
| `tool:relative_strength` | PASS | data (market, derived) |
| `tool:positions` | PASS | data (portfolio, derived) |
| `tool:day_pnl` | PASS | data (portfolio, derived) |
| `tool:concentration` | PASS | data (portfolio, derived) |
| `tool:correlation_matrix` | PASS | data (portfolio, derived) |
| `tool:portfolio_beta` | PASS | data (portfolio, derived) |
| `tool:correlation` | PASS | data (relations, derived) |
| `tool:peer_set` | PASS | data (relations, derived) |
| `tool:event_study` | PASS | data (relations, derived) |
| `tool:sector_proxy` | PASS | data (relations, derived) |
| `tool:peer_moves` | PASS | data (relations, derived) |
| `tool:read_across` | PASS | data (relations, derived) |
| `tool:news` | PASS | data (street) |
| `tool:analyst_ratings` | PASS | data (street) |
| `tool:price_targets` | PASS | data (street) |
| `tool:rating_changes` | PASS | data (street) |
| `tool:institutional_holders` | PASS | data (street) |
| `tool:insider_transactions` | PASS | data (street) |
| `tool:short_interest` | PASS | data (street) |
| `rsi_in_range` | PASS | RSI 60.2 |
| `beta_plausible` | PASS | beta 1.88 |
| `empty_is_not_error` | PASS | TSLA dividends -> empty |
| `domain_populated:market` | PASS | 9 tools |
| `domain_populated:fundamentals` | PASS | 7 tools |
| `domain_populated:street` | PASS | 7 tools |
| `domain_populated:events` | PASS | 4 tools |
| `domain_populated:relations` | PASS | 6 tools |
| `domain_populated:macro` | PASS | 3 tools |
| `domain_populated:portfolio` | PASS | 5 tools |


## Regressions — 19/19

| Case | Result | Detail |
|---|---|---|
| `threshold_5pct` | PASS | [(-7.4, True), (-5.0, True), (-3.1, False), (6.8, True)] |
| `threshold_has_reason` | PASS | read=company-specific — the peer group did not follow |
| `no_duplicate_move_signal` | PASS | ['threshold'] |
| `event_study_dedupe` | PASS | 9 events, 9 unique |
| `event_study_baseline` | PASS | baseline 71.2%, p=0.021 |
| `peers_dynamic` | PASS | {"IREN": ["NBIS", "CRWV", "CIFR", "APLD", "ONDS"], "XOM": ["CVX", "JNJ", "WMT", "PG", "PFE"], "LLY": ["MRK", "BMY", "NVO |
| `sector_proxy_dynamic` | PASS | {"NVDA": "VGT", "KO": "PG+JNJ+VZ", "XOM": "CVX+JNJ+WMT"} |
| `present_rounds` | PASS | shown={'language': 'en-US', 'region': 'US', 'quoteType': 'EQUITY', 'typeDisp': 'Equity'} |
| `present_stays_grounded` | PASS | quoted [230.86, 2.5] |
| `invented_still_fails` | PASS | 77.7 rejected |
| `gate_catches_fabrication` | PASS | gate flagged [88.8] |
| `gate_matches_report` | PASS | gate [88.8] vs report [88.8] |
| `gate_passes_clean` | PASS | no flags |
| `readability_ignores_names` | PASS | good=5/5 soup=2/5 |
| `grounding:dates` | PASS | grounded=True, expected=True |
| `grounding:index names` | PASS | grounded=True, expected=True |
| `grounding:windows` | PASS | grounded=True, expected=True |
| `grounding:unit scaling` | PASS | grounded=True, expected=True |
| `grounding:real fabrication` | PASS | grounded=False, expected=False |


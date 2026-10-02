# Eval report

Run 2026-10-02 01:51 · model `gemini-3.5-flash-lite` · 41 tools · LLM on

**247/247 passed**


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
| `register_succeeds` | PASS | 200 probe-96e0cf4d |
| `register_returns_no_password` | PASS | response carries no password field |
| `username_case_insensitive_unique` | PASS | 409 That username is taken. |
| `session_cookie_works` | PASS | probe-96e0cf4d can_save=True |
| `no_user_enumeration` | PASS | real user: 401 / unknown: 401, same text: True |
| `throttle_locks_out` | PASS | 25 failures -> locked for 899s (limit 5) |
| `ip_budget_is_looser` | PASS | 5 fails -> 0s, 50 -> 899s |
| `throttle_clears_on_success` | PASS | cleared |
| `guest_cannot_write` | PASS | 401 Sign in to keep a watchlist or portfolio. |
| `guest_sees_empty_book` | PASS | 200 [] |
| `guest_keeps_market_data` | PASS | 200 1 quote(s) |
| `register_does_not_adopt` | PASS | fresh account sees ['Brokerage'] |
| `seeded_ids_are_per_user` | PASS | ids ['7b7bb8d96a51'] |
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
| `register_200` | PASS | {'id': '9f690bccf2c0', 'username': 'davidle', 'name': 'David', 'signed |
| `cookie_httponly` | PASS |  |
| `cookie_samesite_lax` | PASS |  |
| `cookie_persists` | PASS |  |
| `me_knows_user` | PASS | David |
| `can_save` | PASS |  |
| `watchlist_write` | PASS | {'watchlist': ['NVDA', 'AAPL', 'MSFT', 'AMD', 'PLTR', 'KO',  |
| `watchlist_read_back` | PASS |  |
| `portfolio_create` | PASS | {'accounts': [{'id': '1f799a2ed283', 'name': 'Brokerage', 'k |
| `logout_204` | PASS |  |
| `logout_returns_to_guest` | PASS |  |
| `guest_cannot_write` | PASS |  |
| `guest_sees_nothing` | PASS |  |
| `login_200` | PASS | {'id': '9f690bccf2c0', 'username': 'davidle', 'name': 'David |
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


## App sweep — 78/78

| Case | Result | Detail |
|---|---|---|
| `index_served` | PASS | 65851 bytes |
| `index_no_store` | PASS | no-store, must-revalidate |
| `asset_stamp_matches_build` | PASS | app.js?v=1790920313 |
| `build_stamp` | PASS | {'build': '1790920313'} |
| `health` | PASS | llm=True model=gemini-3.5-flash-lite tools=41 db=sqlite |
| `health_names_db` | PASS | sqlite |
| `quotes_batched` | PASS | 8 quotes / 1 upstream call(s) |
| `quotes_priced` | PASS | 8/8 priced and named |
| `bars_ohlcv` | PASS | 21 bars |
| `bars_intraday` | PASS | 78 5m bars |
| `sparklines` | PASS | {'NVDA': 21, 'AAPL': 21} |
| `overview` | PASS | cap=5574576046080 pe=28.893618 margin=0.63663 |
| `overview_has_balance_sheet` | PASS | d/e=16.971 fcf=41809874944 |
| `financials` | PASS | 8 quarters, single-quarter only: True |
| `news` | PASS | 12 items, 2 flagged relevant |
| `news_relevance_flagged` | PASS |  |
| `analysts` | PASS | {'Strong buy': 10, 'Buy': 48, 'Hold': 2, 'Sell': 1, 'Strong sell': 0} |
| `analyst_targets` | PASS | {'targetLowPrice': 180.0, 'targetMeanPrice': 327.7, 'targetHighPrice': 515.0} |
| `events` | PASS | 6 past surprises |
| `indices` | PASS | ['S&P 500', 'Dow Jones', 'Nasdaq', 'Fear & Greed', 'Volatility', 'US 10-year'] |
| `no_russell` | PASS |  |
| `fear_greed` | PASS | 28.0 (None) |
| `indices_have_history` | PASS | {'S&P 500': 21, 'Dow Jones': 21, 'Nasdaq': 21, 'Volatility': 23, 'US 10-year': 22} |
| `compare` | PASS | 3 rows, 126 points, 3 pairs |
| `compare_pairwise` | PASS | {'pair': 'AMD/AVGO', 'corr': 0.53} |
| `related` | PASS | ['AMD', 'TSLA', 'AMZN', 'AAPL'] |
| `related_is_measured` | PASS | AMD: corr=0.52 n=500 |
| `related_moves` | PASS | ['ticker', 'ticker_change_pct', 'peer_average_pct', 'peers', 'biggest_mover'] |
| `event_study` | PASS | AMD earnings -> NVDA reaction: 9 events |
| `event_study_direction` | PASS | source=AMD target=NVDA |
| `event_study_deduped` | PASS | 9 events, 9 unique dates |
| `event_study_baseline` | PASS | baseline 69.4%, p=0.284 |
| `search` | PASS | ['KO', 'COKE', 'CCEP', 'KOF', 'COLA.WA'] |
| `logo` | PASS | 200 image/png 11180B |
| `guest_identity` | PASS | Guest |
| `guest_watchlist_empty` | PASS |  |
| `guest_write_401` | PASS |  |
| `guest_portfolios_empty` | PASS |  |
| `guest_create_401` | PASS |  |
| `guest_position_401` | PASS |  |
| `guest_reset_401` | PASS |  |
| `guest_brief_is_macro_only` | PASS | market_only=True, 0 tickers, 10 macro headlines |
| `guest_brief_says_why` | PASS | not signed in |
| `providers` | PASS |  |
| `register` | PASS | {'id': '4933257b4bd3', 'username': 'sweeper', 'name': 'sweep |
| `login_reachable` | PASS |  |
| `watch_add` | PASS |  |
| `watch_rejects_junk` | PASS |  |
| `watch_delete` | PASS |  |
| `account_create` | PASS | 3b4388887ccc |
| `account_name_unique` | PASS |  |
| `account_rename` | PASS |  |
| `account_activate` | PASS |  |
| `position_add` | PASS |  |
| `position_averages_basis` | PASS | qty=20.0 basis=150.0 |
| `portfolio_math` | PASS | $4,617 |
| `combined_view` | PASS | $28,920 across 4 rows |
| `analytics` | PASS | {'weights_pct': [{'ticker': 'NVDA', 'pct': 100.0}], 'top_holding': {'ticker': 'NVDA', 'pct': 100.0}, 'top3_pct': 100.0,  |
| `analytics_beta` | PASS | {'portfolio_beta': 1.88, 'per_holding': [{'ticker': 'NVDA', 'beta': 1.88}], 'reading': 'more volatile than the market'} |
| `position_edit` | PASS | 200 -> qty=5.0 basis=120.0 |
| `position_edit_404s_cleanly` | PASS |  |
| `position_delete` | PASS |  |
| `account_delete` | PASS |  |
| `brief_signals` | PASS | 0 signals over 6 tickers |
| `brief_macro` | PASS | 8 macro headlines |
| `brief_index_levels` | PASS | ['S&P 500', 'Nasdaq', 'US 10-year yield', 'volatility index'] |
| `brief_checks_adjacent` | PASS | 15 adjacent names |
| `threshold_moves_explain_themselves` | PASS | 0 threshold moves, all with a reason: none today |
| `domains_registered` | PASS | ['market', 'fundamentals', 'street', 'events', 'relations', 'macro', 'portfolio'] |
| `every_domain_has_tools` | PASS | all populated |
| `tool_count` | PASS | 41 tools |
| `agent_ask` | PASS | 179 chars in 9s |
| `agent_grounded` | PASS | ungrounded: [] |
| `agent_disclaimer` | PASS | Informational only, not financial advice. Monsoon summarises public da |
| `disclaimer_rendered` | PASS | present in the shell |
| `reset_keeps_watchlist` | PASS |  |
| `reset_clears_positions` | PASS |  |
| `every_route_touched` | PASS | all covered |


## Data plane — 15/15

| Case | Result | Detail |
|---|---|---|
| `quotes_batched` | PASS | 8 quotes in 1 upstream request(s) |
| `bars_shape` | PASS | 21 bars, OHLCV shape True |
| `edgar_single_quarter` | PASS | 8 quarters, all single-quarter: True |
| `financials_outlook` | PASS | next 2026-11-17, eps est 2.47332, 8 past reports |
| `overview/NVDA` | PASS | market_cap=5574576046080 |
| `news/NVDA` | PASS | items=[{'title': 'SPCX Stock Climbs Overnight: Musk Teases ‘Big De |
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


## Regressions — 23/23

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
| `degraded_route_is_declared` | PASS | The router was unavailable, so this was answered from price data alone and may not address |
| `degraded_route_shows_in_trace` | PASS | ROUTER UNAVAILABLE - fell back to market(NVDA) |
| `degraded_route_keeps_the_ticker` | PASS | ['NVDA'] |
| `fallback_ticker_extraction` | PASS | all 4 correct |
| `grounding:dates` | PASS | grounded=True, expected=True |
| `grounding:index names` | PASS | grounded=True, expected=True |
| `grounding:windows` | PASS | grounded=True, expected=True |
| `grounding:unit scaling` | PASS | grounded=True, expected=True |
| `grounding:real fabrication` | PASS | grounded=False, expected=False |


## Agent — 12/12

| Case | Result | Detail |
|---|---|---|
| `single_domain_price` | PASS | domains=['market'] grounded=True |
| `valuation_fundamentals` | PASS | domains=['fundamentals'] grounded=True |
| `street_sentiment` | PASS | domains=['street'] grounded=True |
| `macro_backdrop` | PASS | domains=['macro'] grounded=True |
| `overall_read_pulls_macro` | PASS | domains=['fundamentals', 'macro', 'market', 'street'] grounded=True |
| `read_across` | PASS | domains=['relations'] grounded=True |
| `earnings_outlook` | PASS | domains=['events'] grounded=True |
| `explicit_selection` | PASS | domains=['fundamentals', 'relations'] grounded=True |
| `selection_not_substituted` | PASS | domains=['fundamentals', 'relations'] grounded=True |
| `refuse_offtopic` | PASS | domains=['macro'] grounded=True |
| `refuse_injection` | PASS | domains=[] grounded=True |
| `unknown_ticker_degrades` | PASS | domains=['macro'] grounded=True |


## Answer quality (deterministic)

| Case | Validity | Readability | Structure | Conjunction |
|---|---|---|---|---|
| `single_domain_price` | 5/5 | 5/5 | 3/5 | 1/5 |
| `valuation_fundamentals` | 5/5 | 5/5 | 5/5 | 4/5 |
| `street_sentiment` | 5/5 | 5/5 | 5/5 | 4/5 |
| `macro_backdrop` | 5/5 | 5/5 | 5/5 | 2/5 |
| `overall_read_pulls_macro` | 5/5 | 4/5 | 5/5 | 5/5 |
| `read_across` | 5/5 | 5/5 | 5/5 | 5/5 |
| `earnings_outlook` | 5/5 | 5/5 | 5/5 | 1/5 |
| `explicit_selection` | 5/5 | 5/5 | 5/5 | 5/5 |
| `selection_not_substituted` | 5/5 | 2/5 | 5/5 | 5/5 |
| `unknown_ticker_degrades` | 5/5 | 5/5 | 5/5 | 2/5 |

**Conjunction rate: 6/10 (60%)** — share of answers that relate two tools' or domains' data rather than listing them. This is the metric DESIGN.md §10 says justifies domain subgraphs: a one-tool agent cannot score here by construction.

- mean validity: **5.0/5**
- mean readability: **4.6/5**
- mean structure: **4.8/5**

**Lowest readability**

- `selection_not_substituted` — unreadable: 11 figures in one sentence
- `overall_read_pulls_macro` — 3 figures in one sentence
- `single_domain_price` — 2 sentences, 7 words each, max 2 figure(s) per sentence

## Agent cost & latency

- median tokens/run: **2302**
- median latency: **8.5s** (p95 18.7s)
- median LLM calls: **3**

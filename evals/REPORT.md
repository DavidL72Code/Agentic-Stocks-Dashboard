# Eval report

Run 2026-10-09 16:25 · model `gemini-3.5-flash-lite` · 45 tools · LLM on

**345/345 passed**


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
| `register_succeeds` | PASS | 200 probe-4143a097 |
| `register_returns_no_password` | PASS | response carries no password field |
| `username_case_insensitive_unique` | PASS | 409 That username is taken. |
| `session_cookie_works` | PASS | probe-4143a097 can_save=True |
| `no_user_enumeration` | PASS | real user: 401 / unknown: 401, same text: True |
| `throttle_locks_out` | PASS | 25 failures -> locked for 899s (limit 5) |
| `ip_budget_is_looser` | PASS | 5 fails -> 0s, 50 -> 899s |
| `throttle_clears_on_success` | PASS | cleared |
| `guest_cannot_write` | PASS | 401 Sign in to keep a watchlist or portfolio. |
| `guest_sees_empty_book` | PASS | 200 [] |
| `guest_keeps_market_data` | PASS | 200 1 quote(s) |
| `register_does_not_adopt` | PASS | fresh account sees ['Brokerage'] |
| `seeded_ids_are_per_user` | PASS | ids ['7604d223385a'] |
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
| `register_200` | PASS | {'id': '499d99561854', 'username': 'davidle', 'name': 'David', 'signed |
| `cookie_httponly` | PASS |  |
| `cookie_samesite_lax` | PASS |  |
| `cookie_persists` | PASS |  |
| `me_knows_user` | PASS | David |
| `can_save` | PASS |  |
| `watchlist_write` | PASS | {'watchlist': ['NVDA', 'AAPL', 'MSFT', 'AMD', 'PLTR', 'KO',  |
| `watchlist_read_back` | PASS |  |
| `portfolio_create` | PASS | {'accounts': [{'id': '1853b2e07769', 'name': 'Brokerage', 'k |
| `logout_204` | PASS |  |
| `logout_returns_to_guest` | PASS |  |
| `guest_cannot_write` | PASS |  |
| `guest_sees_nothing` | PASS |  |
| `login_200` | PASS | {'id': '499d99561854', 'username': 'davidle', 'name': 'David |
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


## App sweep — 92/92

| Case | Result | Detail |
|---|---|---|
| `index_served` | PASS | 85025 bytes |
| `index_no_store` | PASS | no-store, must-revalidate |
| `asset_stamp_matches_build` | PASS | app.js?v=1791577523 |
| `build_stamp` | PASS | {'build': '1791577523'} |
| `no_store_api_me` | PASS | no-store, private |
| `no_store_api_portfolio` | PASS | no-store, private |
| `no_store_api_watchlist` | PASS | no-store, private |
| `no_store_api_quotes` | PASS | no-store, private |
| `no_store_api_health` | PASS | no-store, private |
| `varies_on_cookie` | PASS | Cookie |
| `cors_rejects_unknown_origin` | PASS | allow-origin: None for Origin https://evil.example |
| `cors_allows_own_origin` | PASS | http://127.0.0.1:8077 -> 'http://127.0.0.1:8077' |
| `cors_never_allows_credentials` | PASS | None |
| `cors_preflight_denies_unknown_origin` | PASS | preflight -> None |
| `health` | PASS | llm=True model=gemini-3.5-flash-lite tools=45 db=sqlite |
| `health_names_db` | PASS | sqlite |
| `quotes_batched` | PASS | 8 quotes / 1 upstream call(s) |
| `quotes_priced` | PASS | 8/8 priced and named |
| `bars_ohlcv` | PASS | 22 bars |
| `bars_intraday` | PASS | 78 5m bars |
| `sparklines` | PASS | {'NVDA': 22, 'AAPL': 22} |
| `overview` | PASS | cap=5536424132608 pe=28.986094 margin=0.6365999999999999 |
| `overview_has_balance_sheet` | PASS | d/e=16.971 fcf=41809874944 |
| `financials` | PASS | 8 quarters, single-quarter only: True |
| `news` | PASS | 12 items, 2 flagged relevant |
| `news_relevance_flagged` | PASS |  |
| `analysts` | PASS | {'Strong buy': 10, 'Buy': 48, 'Hold': 2, 'Sell': 1, 'Strong sell': 0} |
| `analyst_targets` | PASS | {'targetLowPrice': 180.0, 'targetMeanPrice': 328.71695, 'targetHighPrice': 515.0} |
| `events` | PASS | 6 past surprises |
| `indices` | PASS | ['S&P 500', 'Dow Jones', 'Nasdaq', 'Fear & Greed', 'Volatility', 'US 10-year'] |
| `no_russell` | PASS |  |
| `fear_greed` | PASS | 45 (None) |
| `indices_have_history` | PASS | {'S&P 500': 22, 'Dow Jones': 22, 'Nasdaq': 22, 'Volatility': 23, 'US 10-year': 23} |
| `compare` | PASS | 3 rows, 128 points, 3 pairs |
| `compare_pairwise` | PASS | {'pair': 'AMD/AVGO', 'corr': 0.54} |
| `compare_rejects_markup` | PASS | 400 |
| `earnings_week` | PASS | 8 of 130 reporting ·  |
| `related` | PASS | ['AMD', 'TSLA', 'AMZN', 'AAPL'] |
| `related_is_measured` | PASS | AMD: corr=0.53 n=501 |
| `related_moves` | PASS | ['ticker', 'ticker_change_pct', 'peer_average_pct', 'peers', 'biggest_mover'] |
| `event_study` | PASS | AMD earnings -> NVDA reaction: 9 events |
| `event_study_direction` | PASS | source=AMD target=NVDA |
| `event_study_deduped` | PASS | 9 events, 9 unique dates |
| `event_study_baseline` | PASS | baseline 69.3%, p=0.108 |
| `search` | PASS | ['KO', 'COKE', 'KOF', 'CCEP', 'COLA.WA'] |
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
| `register` | PASS | {'id': '589026e9aee7', 'username': 'sweeper', 'name': 'sweep |
| `login_reachable` | PASS |  |
| `watch_add` | PASS |  |
| `watch_rejects_junk` | PASS |  |
| `watch_delete` | PASS |  |
| `account_create` | PASS | 80f9a5cf95cb |
| `account_name_unique` | PASS |  |
| `account_rename` | PASS |  |
| `account_activate` | PASS |  |
| `position_add` | PASS |  |
| `position_averages_basis` | PASS | qty=20.0 basis=150.0 |
| `portfolio_math` | PASS | $4,586 |
| `combined_view` | PASS | $29,203 across 4 rows |
| `analytics` | PASS | {'weights_pct': [{'ticker': 'NVDA', 'pct': 100.0}], 'top_holding': {'ticker': 'NVDA', 'pct': 100.0}, 'top3_pct': 100.0,  |
| `analytics_beta` | PASS | {'portfolio_beta': 1.89, 'per_holding': [{'ticker': 'NVDA', 'beta': 1.89}], 'reading': 'more volatile than the market'} |
| `position_edit` | PASS | 200 -> qty=5.0 basis=120.0 |
| `position_edit_404s_cleanly` | PASS |  |
| `position_delete` | PASS |  |
| `account_delete` | PASS |  |
| `brief_signals` | PASS | 6 signals over 6 tickers |
| `brief_macro` | PASS | 8 macro headlines |
| `brief_index_levels` | PASS | ['S&P 500', 'Nasdaq', 'US 10-year yield', 'volatility index'] |
| `brief_checks_adjacent` | PASS | 15 adjacent names |
| `threshold_moves_explain_themselves` | PASS | 1 threshold moves, all with a reason: True |
| `domains_registered` | PASS | ['market', 'fundamentals', 'street', 'events', 'relations', 'macro', 'screener', 'portfolio'] |
| `every_domain_has_tools` | PASS | all populated |
| `tool_count` | PASS | 45 tools |
| `reset_keeps_watchlist` | PASS |  |
| `reset_clears_positions` | PASS |  |
| `env_documented_in_HOSTING_md` | PASS | all 24 documented |
| `env_documented_in_env_example` | PASS | all 24 documented |
| `cookie_secure_warns_when_insecure` | PASS | startup warns on a non-https APP_BASE_URL |
| `dockerignore_exists` | PASS | .dockerignore |
| `dockerignore_blocks_secrets` | PASS | all 6 excluded |
| `dockerignore_keeps_the_app` | PASS | all 5 present |
| `every_route_touched` | PASS | all covered |


## Tenancy — 34/34

| Case | Result | Detail |
|---|---|---|
| `accounts_not_shared` | PASS | alice sees ['Alice Roth', 'Brokerage'] |
| `watchlist_not_shared` | PASS | alice: ['AAPL', 'AMD', 'KO', 'MSFT', 'NVDA', 'PLTR'] |
| `combined_view_is_own_only` | PASS | ['NVDA', 'AAPL', 'MSFT', 'KO'] |
| `read_foreign_portfolio_empty` | PASS | 0 rows, $0.0 |
| `read_foreign_portfolio_leaks_no_name` | PASS | All accounts |
| `analytics_on_foreign_id_is_empty` | PASS | concentration=None |
| `rename_foreign_account_denied` | PASS | 404 |
| `rename_had_no_effect` | PASS | ['Bob Roth', 'Brokerage'] |
| `insert_into_foreign_account_denied` | PASS | bob holds ['XOM'] (request returned 400) |
| `edit_foreign_position_denied` | PASS | 404; bob's XOM qty still 77.0 |
| `delete_foreign_position_denied` | PASS | 404; bob still holds ['XOM'] |
| `activate_foreign_account_denied` | PASS | 404 |
| `reset_foreign_id_rejected` | PASS | 404 |
| `reset_cannot_wipe_foreign_account` | PASS | bob's book intact |
| `reset_foreign_id_spares_own_watchlist` | PASS | ['AAPL', 'AMD', 'KO', 'MSFT', 'NVDA', 'PLTR'] still there |
| `delete_foreign_account_denied` | PASS | 404 (was 200 - a silent no-op reported as success) |
| `delete_foreign_had_no_effect` | PASS | bob's account still exists |
| `per_account_reset_clears_that_account` | PASS | 200, 0 positions left |
| `per_account_reset_keeps_watchlist` | PASS | 7 before, 7 after |
| `per_account_reset_spares_other_accounts` | PASS | alice's other accounts still hold ['NVDA', 'AAPL', 'MSFT'] |
| `cannot_change_another_password` | PASS | alice's rotation did not touch bob |
| `cannot_delete_another_account` | PASS | 400 |
| `positions_carries_user_id` | PASS | ['basis', 'id', 'portfolio_id', 'qty', 'ticker', 'user_id'] |
| `positions_scope_invariant_holds` | PASS | 0 rows disagree with their portfolio's owner |
| `every_position_row_is_owned` | PASS | {'494ceac9d7da': 3, 'c8f8acc99f56': 4} |
| `direct_user_scoped_query_works` | PASS | alice's rows by user_id alone: ['AAPL', 'MSFT', 'NVDA'] |
| `foreign_keys_enforced` | PASS | ON |
| `backfill_assigns_the_right_owner` | PASS | [('u1', 'KO'), ('u1', 'PEP'), ('u2', 'XOM')] |
| `backfill_leaves_no_mismatch` | PASS | 0 |
| `tools_see_only_anns_book` | PASS | own KO: present, foreign none, local-leak no |
| `tools_see_only_bens_book` | PASS | own XOM: present, foreign none, local-leak no |
| `concurrent_reads_never_cross` | PASS | 24 reads, each its own |
| `lost_context_sees_no_holdings` | PASS | resolved to 'guest', saw [] / [] |
| `lost_context_cannot_write` | PASS | store.save() raises for a context-less caller |


## Cache — 21/21

| Case | Result | Detail |
|---|---|---|
| `l2_off_by_default` | PASS | REDIS_URL='', L2=None |
| `l1_still_caches` | PASS | 1 upstream call(s) for 2 reads |
| `key_is_prefixed_and_labelled` | PASS | monsoon:v1:bars:b3bdeb923c8940d0fb35 |
| `key_no_separator_collision` | PASS | 94c72472ffe2 vs c33762c4f07c |
| `key_is_stable` | PASS | same input, same key |
| `key_distinguishes_symbols` | PASS | NVDA != AMD |
| `round_trip_is_lossless` | PASS | wrote 100B, read back equal: True |
| `round_trip_not_stale` | PASS | stale=False |
| `miss_returns_none` | PASS | None |
| `expired_value_is_kept_but_flagged` | PASS | value survived, stale=True |
| `physical_ttl_outlives_logical` | PASS | logical 60s -> physical 720s (expected ~720s) |
| `unserialisable_is_skipped_not_fatal` | PASS | not_json counter 0 -> 1 |
| `unserialisable_is_not_written` | PASS | nothing stored |
| `failures_trip_the_breaker` | PASS | 3 errors in 2ms -> paused |
| `paused_calls_are_free` | PASS | 100 ops in 0.0ms |
| `breaker_reports_itself` | PASS | ConnectionError: Error 61 connecting to 127.0.0.1:1. Connect |
| `cached_writes_through_to_l2` | PASS | 1 L2 write(s) |
| `survives_an_l1_wipe` | PASS | 1 upstream call(s) across a cleared L1 |
| `l2_hit_is_promoted_to_l1` | PASS | present in L1 after an L2 hit |
| `live_prices_are_not_ttl_cached` | PASS | quote()/quotes() go straight through BatchLoader |
| `bars_are_cached` | PASS | bars() goes through cached() |


## Data plane — 15/15

| Case | Result | Detail |
|---|---|---|
| `quotes_batched` | PASS | 8 quotes in 1 upstream request(s) |
| `bars_shape` | PASS | 22 bars, OHLCV shape True |
| `edgar_single_quarter` | PASS | 8 quarters, all single-quarter: True |
| `financials_outlook` | PASS | next 2026-11-17, eps est 2.47325, 8 past reports |
| `overview/NVDA` | PASS | market_cap=5536424132608 |
| `news/NVDA` | PASS | items=[{'title': 'Nvidia Stocks Edge Higher as $1 Billion Science  |
| `analysts/NVDA` | PASS | distribution=[{'label': 'Strong buy', 'n': 10}, {'label': 'Buy', 'n': 48} |
| `events/NVDA` | PASS | surprise_history=[{'date': '2026-08-26', 'estimate': 2.09, 'actual': 2.22, 's |
| `indices` | PASS | indices=[{'symbol': '^GSPC', 'label': 'S&P 500', 'level': 7811.54, ' |
| `compare` | PASS | correlations=[{'pair': 'AMD/AVGO', 'corr': 0.54}, {'pair': 'NVDA/AVGO', ' |
| `related/NVDA` | PASS | read_across={'ticker': 'NVDA', 'peers': [{'peer': 'AMD', 'peer_name': 'A |
| `portfolio/analytics` | PASS | concentration={'weights_pct': [{'ticker': 'NVDA', 'pct': 46.6}, {'ticker': |
| `search` | PASS | results=[{'symbol': 'KO', 'name': 'Coca-Cola Company (The)', 'type': |
| `fear_greed` | PASS | score 45 (fear) |
| `indices_set` | PASS | ['S&P 500', 'Dow Jones', 'Nasdaq', 'Fear & Greed', 'Volatility', 'US 10-year'] |


## Tools — 56/56

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
| `tool:peer_performance` | PASS | data (relations, derived) |
| `tool:peer_moves` | PASS | data (relations, derived) |
| `tool:read_across` | PASS | data (relations, derived) |
| `tool:screen_stocks` | PASS | data (screener) |
| `tool:cap_movers` | PASS | data (screener, derived) |
| `tool:news` | PASS | data (street) |
| `tool:news_history` | PASS | data (street) |
| `tool:analyst_ratings` | PASS | data (street) |
| `tool:price_targets` | PASS | data (street) |
| `tool:rating_changes` | PASS | data (street) |
| `tool:institutional_holders` | PASS | data (street) |
| `tool:insider_transactions` | PASS | data (street) |
| `tool:short_interest` | PASS | data (street) |
| `rsi_in_range` | PASS | RSI 53.0 |
| `beta_plausible` | PASS | beta 1.89 |
| `empty_is_not_error` | PASS | TSLA dividends -> empty |
| `domain_populated:market` | PASS | 9 tools |
| `domain_populated:fundamentals` | PASS | 7 tools |
| `domain_populated:street` | PASS | 8 tools |
| `domain_populated:events` | PASS | 4 tools |
| `domain_populated:relations` | PASS | 7 tools |
| `domain_populated:macro` | PASS | 3 tools |
| `domain_populated:screener` | PASS | 2 tools |
| `domain_populated:portfolio` | PASS | 5 tools |


## Regressions — 59/59

| Case | Result | Detail |
|---|---|---|
| `threshold_5pct` | PASS | [(-7.4, True), (-5.0, True), (-3.1, False), (6.8, True)] |
| `threshold_has_reason` | PASS | read=moved further than its peer group, which leaned the same way |
| `no_duplicate_move_signal` | PASS | ['threshold', 'peer_move'] |
| `event_study_dedupe` | PASS | 9 events, 9 unique |
| `event_study_baseline` | PASS | baseline 71.7%, p=0.019 |
| `peers_dynamic` | PASS | {"IREN": ["NBIS", "CRWV", "CIFR", "APLD", "ONDS"], "XOM": ["CVX", "JNJ", "WMT", "PG", "PFE"], "LLY": ["MRK", "BMY", "NVO |
| `sector_proxy_dynamic` | PASS | {"NVDA": "VGT", "KO": "PG+JNJ+VZ", "XOM": "CVX+JNJ+WMT"} |
| `present_rounds` | PASS | shown={'language': 'en-US', 'region': 'US', 'quoteType': 'EQUITY', 'typeDisp': 'Equity'} |
| `present_stays_grounded` | PASS | quoted [229.28] |
| `invented_still_fails` | PASS | 77.7 rejected |
| `gate_catches_fabrication` | PASS | gate flagged [88.8] |
| `gate_matches_report` | PASS | gate [88.8] vs report [88.8] |
| `gate_passes_clean` | PASS | no flags |
| `readability_ignores_names` | PASS | good=5/5 soup=2/5 |
| `peer_perf_has_cohort` | PASS | 5 peers measured |
| `peer_perf_beta_adjusts` | PASS | beta 1.89, excess -13.26% |
| `peer_perf_carries_size` | PASS | caps present for the top peers |
| `peer_perf_excess_is_correct` | PASS | -13.26 vs recomputed -13.26 |
| `perf_question_detected` | PASS | all 7 correct |
| `degraded_route_is_declared` | PASS | The router was unavailable, so this was answered from price data alone and may not address |
| `degraded_route_shows_in_trace` | PASS | ROUTER UNAVAILABLE - fell back to market(NVDA) |
| `degraded_route_keeps_the_ticker` | PASS | ['NVDA'] |
| `fallback_ticker_extraction` | PASS | all 4 correct |
| `grounding:dates` | PASS | grounded=True, expected=True |
| `grounding:index names` | PASS | grounded=True, expected=True |
| `grounding:windows` | PASS | grounded=True, expected=True |
| `grounding:unit scaling` | PASS | grounded=True, expected=True |
| `grounding:real fabrication` | PASS | grounded=False, expected=False |
| `edgar_current_tag` | PASS | newest MSFT revenue quarter 2026-06-30 (101 days old) |
| `edgar_no_missing_q4` | PASS | gaps between quarters [92, 92, 90, 91, 92, 92, 90, 91] |
| `edgar_q4_derived` | PASS | derived Q4 = 130 (year 400 less 3 x 90) |
| `growth_is_current` | PASS | latest_quarter_end=2026-06-30 yoy=17.747 |
| `leverage_ratio_not_percent` | PASS | keys=['current_ratio', 'debt_as_pct_of_equity', 'debt_to_equity_ratio', 'net_cash_usd', 'quick_ratio', 'total_cash'] ratio=0.17 |
| `writer_keeps_every_finding` | PASS | 9926 chars, narratives kept: 7/7 |
| `models_split_half_half` | PASS | 5 x gemini-3.5-flash-lite, 5 x gemini-3.1-flash-lite |
| `models_select_on_flash_lite` | PASS | ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'] |
| `model_fallback_on_daily_cap` | PASS | gemini-3.5-flash-lite out of quota -> answered by gemini-3.1-flash-lite |
| `answer_cache_per_user` | PASS | same question, two users -> different keys; B sees A's answer: False |
| `answer_cache_hits` | PASS | identical question from the same user is served from cache |
| `stream_answer_decoded` | PASS | 16 pieces -> 'NVDA rose 2.4% — on "thin" volume.\nNext.' |
| `router_sees_every_tool` | PASS | 45 tools across 8 domains |
| `screen_args_backstop` | PASS | {'style': 'momentum', 'cap': 'micro', 'sector': 'Technology'} |
| `screen_sector_exact` | PASS | ['Technology', 'Health Care', 'Technology'] |
| `market_followups_only_market_domains` | PASS | {'MARKET': ['screener']} |
| `screened_names_can_be_dug_into` | PASS | {'SHAZ': ['market', 'fundamentals', 'street', 'events', 'relations'], 'UMAC': ['market', 'fundamentals', 'street', 'events', 'relations']} |
| `cite_nearest_company` | PASS | {'107.6%': ['https://example.com/amd'], '-13.1%': ['https://example.com/nvda'], '$8.2 billion': ['https://news.example/a']} |
| `cite_headline_figure` | PASS | {'107.6%': ['https://example.com/amd'], '-13.1%': ['https://example.com/nvda'], '$8.2 billion': ['https://news.example/a']} |
| `cite_segments_rebuild_answer` | PASS | segments concatenate back to the answer |
| `cite_urls_are_http` | PASS | ['https://example.com/amd', 'https://example.com/nvda', 'https://news.example/a', 'https://example.com/news'] |
| `cite_field_level_source` | PASS | {'14.43': ['https://finance.yahoo.com/quote/NVDA/analysis/'], '$5.55T': ['https://finance.yahoo.com/quote/NVDA/']} |
| `url_digits_never_ground` | PASS | [1045810.0] |
| `ytd_from_prior_year_close` | PASS | ytd base 186.06, 3 closes |
| `ttm_margins_from_four_filings` | PASS | {'operating_margin_pct': 65.21, 'net_margin_pct': 63.66, 'gross_margin_pct': 74.67} |
| `ttm_refuses_a_gap` | PASS | None |
| `chart_for_a_comparison` | PASS | [{'kind': 'bars', 'title': 'Margins over the last 12 months', 'unit': '%', 'series': [{'key': 'gross_margin', 'label': 'Gross'}, {'key': 'operating_ma |
| `no_chart_unless_needed` | PASS | [[], []] |
| `chart_lines_for_returns` | PASS | [[{'kind': 'lines', 'period': '1y', 'symbols': ['NVDA', 'SPY'], 'labels': {'SPY': 'S&P 500'}, 'title': 'NVDA vs the S&P 500, the past year', 'note': ' |
| `chart_returns_first` | PASS | [('lines', ['NVDA', 'AMD']), ('bars', None)] |
| `subgraph_steps_accumulate` | PASS | steps reducer: (<built-in function add>,) |


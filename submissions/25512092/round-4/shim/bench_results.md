# claude -p shim benchmark

2026-11-22 17:04, 10 calls per config through agent_kit.Model.complete, kit WORLD+FORMAT system prompt, prompt growing turn by turn, 3 s between calls.

| model | prewarm | mean s | median s | max s | strict JSON | kit parse | errors | prompt chars (first-last) |
|---|---|---|---|---|---|---|---|---|
| sonnet | on (2) | 4.5 | 3.9 | 8.1 | 9/10 | 9/10 | 1 | 10,189-15,733 |
| sonnet | off | 5.7 | 5.4 | 7.9 | 9/10 | 9/10 | 1 | 10,189-16,680 |
| haiku | on (2) | 5.4 | 5.1 | 11.5 | 9/10 | 9/10 | 1 | 10,189-15,408 |
| haiku | off | 6.5 | 6.5 | 8.3 | 8/10 | 9/10 | 1 | 10,189-20,746 |

Per call:

```
sonnet pool=2 #0   2.75s chars= 10189 strict=True  parsed=True  action=app_owner_memo out=153 
sonnet pool=2 #1   4.61s chars= 10455 strict=True  parsed=True  action=forge_tool out=943 
sonnet pool=2 #2   8.08s chars= 11541 strict=True  parsed=True  action=forge_tool out=914 
sonnet pool=2 #3   2.76s chars= 12508 strict=True  parsed=True  action=read_card out=208 
sonnet pool=2 #4   3.53s chars= 13257 strict=True  parsed=True  action=read_card out=343 
sonnet pool=2 #5   3.31s chars= 13654 strict=True  parsed=True  action=read_tool out=240 
sonnet pool=2 #6   3.86s chars= 14034 strict=True  parsed=True  action=read_tool out=324 
sonnet pool=2 #7   5.23s chars= 14955 strict=True  parsed=True  action=read_card out=438 
sonnet pool=2 #8   6.41s chars= 15491 strict=True  parsed=True  action=read_tool out=186 
sonnet pool=2 #9   4.22s chars= 15733 strict=False parsed=False action=None out=0 KeyError: 'choices'
sonnet pool=0 #0   4.75s chars= 10189 strict=True  parsed=True  action=app_owner_memo out=180 
sonnet pool=0 #1   7.09s chars= 10482 strict=True  parsed=True  action=forge_tool out=1698 
sonnet pool=0 #2   7.86s chars= 12323 strict=True  parsed=True  action=forge_tool out=1365 
sonnet pool=0 #3   4.56s chars= 13741 strict=True  parsed=True  action=fetch_card out=309 
sonnet pool=0 #4   6.22s chars= 14591 strict=True  parsed=True  action=fetch_card out=333 
sonnet pool=0 #5   4.15s chars= 14978 strict=True  parsed=True  action=read_tool out=230 
sonnet pool=0 #6   4.06s chars= 15348 strict=False parsed=False action=None out=0 KeyError: 'choices'
sonnet pool=0 #7   5.41s chars= 15947 strict=True  parsed=True  action=read_tool out=241 
sonnet pool=0 #8   4.90s chars= 16286 strict=True  parsed=True  action=read_tool out=338 
sonnet pool=0 #9   6.45s chars= 16680 strict=True  parsed=True  action=forge_tool out=1018 
haiku  pool=2 #0   5.50s chars= 10189 strict=True  parsed=True  action=app_owner_memo out=222 
haiku  pool=2 #1  10.60s chars= 10524 strict=False parsed=False action=None out=0 KeyError: 'choices'
haiku  pool=2 #2   7.08s chars= 10669 strict=True  parsed=True  action=write_note out=508 
haiku  pool=2 #3   3.63s chars= 11230 strict=True  parsed=True  action=read_card out=273 
haiku  pool=2 #4   5.09s chars= 12044 strict=True  parsed=True  action=read_card out=288 
haiku  pool=2 #5   3.82s chars= 12386 strict=True  parsed=True  action=market_get out=247 
haiku  pool=2 #6   3.49s chars= 12773 strict=True  parsed=True  action=read_card out=577 
haiku  pool=2 #7  11.52s chars= 13947 strict=True  parsed=True  action=write_note out=896 
haiku  pool=2 #8   5.20s chars= 14941 strict=True  parsed=True  action=read_tool out=411 
haiku  pool=2 #9   2.88s chars= 15408 strict=True  parsed=True  action=read_tool out=517 
haiku  pool=0 #0   4.93s chars= 10189 strict=False parsed=False action=None out=0 KeyError: 'choices'
haiku  pool=0 #1   8.16s chars= 10304 strict=True  parsed=True  action=forge_tool out=1948 
haiku  pool=0 #2   8.26s chars= 12395 strict=True  parsed=True  action=write_note out=719 
haiku  pool=0 #3   4.68s chars= 13167 strict=True  parsed=True  action=read_card out=330 
haiku  pool=0 #4   6.93s chars= 14038 strict=True  parsed=True  action=forge_tool out=1703 
haiku  pool=0 #5   6.02s chars= 15795 strict=False parsed=True  action=read_tool out=562 
haiku  pool=0 #6   6.50s chars= 16497 strict=True  parsed=True  action=wholesale_catalog out=543 
haiku  pool=0 #7   6.36s chars= 17637 strict=True  parsed=True  action=write_note out=1031 
haiku  pool=0 #8   6.66s chars= 18766 strict=True  parsed=True  action=forge_tool out=1924 
haiku  pool=0 #9   5.36s chars= 20746 strict=True  parsed=True  action=shop_inventory out=354 
```

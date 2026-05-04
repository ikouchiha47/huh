# /huh search-path — Check if a file or directory is already indexed

Before reading a large file, check whether a summary already exists in memory.

## Steps

### 1. Check for existing index

```bash
huh search-path <path> --limit 5
```

### 2. Interpret results

- **Results found**: read the summaries. If they are fresh (not marked stale), use them as context instead of opening the full file. Report what was found.
- **No results**: proceed to read the file normally. Consider running `/huh index <path>` after reading it.
- **Stale results**: the episode has the tag `stale` — meaning the file was written or edited after the index was saved, so the summary no longer matches the current content. Read the file and re-index it with `/huh index <path>`. A result is stale if any episode for that path contains `"stale"` in its tags list.

### 3. Report

Tell the user whether an existing summary was found and whether it was used.

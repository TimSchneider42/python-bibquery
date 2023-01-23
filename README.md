# BibQuery
A tool for creating BibTeX entries from links using BibItNow (https://github.com/Langenscheiss/bibitnow) and Selenium.

## Installation
This library can be installed via pip:
```bash
pip install bibquery
```

## Usage
To use _bibquery_ from the command line, type
```bash
bibquery https://arxiv.org/abs/1706.03762
```

If you want to use it inside your python application, you can do so as follows:
```python
from bibquery import BibQuery, query, query_batch

# Option 1
with BibQuery() as bq:
    print(bq.query("https://arxiv.org/abs/1706.03762"))

# Option 2
print(query("https://arxiv.org/abs/1706.03762"))
# Do not use query in a for-loop, as it will recreate the Selenium browser on every call. Rather use option 1 or 3 if
# you need to make multiple calls.

# Option 3
print(query_batch(["https://arxiv.org/abs/1706.03762", "https://ieeexplore.ieee.org/abstract/document/726791"]))

```
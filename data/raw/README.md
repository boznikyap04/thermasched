# Raw datasets (not in git)

Put the raw files here. They are too large for GitHub, so everything in this folder
except this README is ignored by git. Ask the project owner for a copy.

```
data/raw/
├── UniMelb.csv              server telemetry (613 MB)
└── UFCG/                    OpenStack VM trace (about 8 GB)
    ├── servers_usage.csv
    ├── servers_specs.csv
    ├── flavors.csv
    └── ...                  other UFCG files, not read
```

Only `notebooks/data_prep.ipynb` reads them. See the
[cleaning notebook guide](../../notebooks/README.md).

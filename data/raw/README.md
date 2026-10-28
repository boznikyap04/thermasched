# Raw datasets (not in git)

Put the raw files here. They are too large for GitHub, so everything in this folder
except this README is ignored by git. Ask the project owner for a copy.

```
data/raw/
├── UniMelb.csv              server telemetry, Dell R840 servers (613 MB)
├── UniMelb_C6320.csv        server telemetry, Dell C6320 servers (184 MB)
└── UFCG/                    OpenStack VM trace (about 8 GB)
    ├── servers_usage.csv
    ├── servers_specs.csv
    ├── flavors.csv
    └── ...                  other UFCG files, not read
```

The two UniMelb files are the two datasets of Zenodo record
[10.5281/zenodo.10069402](https://zenodo.org/records/10069402) (Ilager et al., UCC 2023),
renamed:

| File here | File in the record | Bytes | MD5 |
|---|---|---|---|
| `UniMelb.csv` | `dataset1_combined.csv` (D1: 81 R840 hosts, Oct 2018 - Jun 2019) | 613,212,066 | `0b931f2b2cc4f236ef9b66e2716b69b2` |
| `UniMelb_C6320.csv` | `dataset2_combined.csv` (D2: 64 C6320 hosts, Feb - Jun 2019; no inlet or fan columns) | 184,178,675 | `8660d51cfb62dfc15f65c79406cb715f` |

Only `notebooks/data_prep.ipynb` reads them. See the
[cleaning notebook guide](../../notebooks/README.md).

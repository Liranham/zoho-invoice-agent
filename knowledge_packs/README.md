# Goldman knowledge packs

Reference material for Goldman, the CFO agent. Each pack is a single
Markdown file structured with H2 sections (clean chunk boundaries).

## Add a pack

After editing a pack file:

```bash
python3 cli.py pack add knowledge_packs/<file>.md \
  --topic <topic_slug> --version v<N>-YYYY-MM
python3 cli.py db embed-pending
```

`pack add` uploads to Supabase Storage at `packs/{topic}/{version}/`,
inserts a `goldman.documents` row with `source='knowledge_pack'`, and
chunks the file at 512-token windows with 64-token overlap. `db
embed-pending` then generates the OpenAI embeddings.

## Citation behaviour

Goldman cites pack chunks as "per the [topic] reference pack v[version]"
and uploaded documents (your accountant's letters) as "per [filename]".
When both are relevant he shows both — the pack is the rule, the letters
are the specifics for your company.

## Current packs

- `us_llc_tax_v1.md` — US federal tax rules for foreign-owned
  single-member LLCs. Covers Form 5472, ECI, state considerations,
  filing calendar, EIN/ITIN/SSN, withholding, contractor vs employee,
  penalty triggers.
- `hk_profits_tax_v1.md` — Hong Kong profits tax for HK-incorporated
  companies. Covers the territorial source principle, two-tier rate,
  offshore profits claim, filing calendar, documentation requirements,
  common foot-guns, audit patterns, tax incentives, cross-border
  considerations.
- `transfer_pricing_hk_us_v1.md` — Transfer pricing for HK-US
  intercompany transactions between AMZ Expert Global Limited and
  Specific Edge Outsourcing LLC. Covers arm's-length principle, OECD
  methods, documentation requirements both sides, common intercompany
  structures, audit risks.

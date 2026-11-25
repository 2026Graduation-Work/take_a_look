# Take a Look

**A decision-support service for first-time stock investors** (Korean market, KOSPI)

Graduation project, Department of Software, Sungkyunkwan University (2026). The app itself is in Korean; this page is a short English summary of the [Korean README](README.md).

- **Live demo**: https://takealook-skku.vercel.app. No sign-up needed: use "데모로 둘러보기" (browse as demo).
- **Submitted version**: tag [`v1.1.0`](https://github.com/2026Graduation-Work/take_a_look/releases/tag/v1.1.0) (2026-10-27). `main` continues with follow-up research ([Co-Deep 2026-2](https://github.com/2026Graduation-Work/take_a_look/milestone/1)).

## What it does

Take a Look applies behavioral finance to help beginners check their own reasoning. It does not tell anyone what to buy or sell.

- **Investor profile**: a 16-question survey (8 axes) finds the user's investing style. The profile decides the order in which evidence is shown and which cautions appear. It never hides a stock.
- **Evidence in a fixed reading order**: each stock shows four kinds of evidence (market mood, who bought and sold, financial health, what the model looked at), each with its comparison group and source.
- **Model signals as one input among several**: a LightGBM model scores KOSPI stocks for 1-week and 4-week horizons. The app explains past outcomes instead of promising future ones, for example "in similar past cases, 7 out of 10 ended within this range". It does not draw future price lines.
- **Holdings from a screenshot**: text in a brokerage app screenshot is read on the device, and the image is never uploaded.

## Design principles

- **Deterministic scores**: every score comes from fixed rules or the model. LLMs only write explanation sentences.
- **The user decides**: no automated trading and no buy or sell instructions. A review signal is labeled as "not a sell instruction".
- **Honest data**: values that are not real data are marked as examples in the UI.

## Run locally

Requires Node 22 and pnpm.

```bash
git clone https://github.com/2026Graduation-Work/take_a_look.git
cd take_a_look/frontend
pnpm install
cp .env.example .env.local
pnpm dev   # http://localhost:3000
```

The Python parts (survey scoring, chart model, news and financial text) each have their own `requirements.txt`. Check a block with `ruff check . && pytest`.

## Contributing

Issues labeled [good first issue](https://github.com/2026Graduation-Work/take_a_look/labels/good%20first%20issue) and [help wanted](https://github.com/2026Graduation-Work/take_a_look/labels/help%20wanted) are open to anyone. Please comment on an issue before you start. The workflow is in [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) (Korean). Report security problems through [SECURITY.md](SECURITY.md), not public issues.

## License

[MIT](LICENSE)

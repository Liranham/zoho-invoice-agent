# US LLC Tax — Reference Pack v1 (2026-06)

This pack is canonical reference material for a foreign-owned
**single-member** US LLC (Specific Edge Outsourcing LLC, owned by AMZ
Expert Global Limited Hong Kong). It does NOT cover multi-member LLCs,
US-resident-owned LLCs, or C-corp / S-corp structures. Where rules
differ for those, this pack notes it briefly and stops.

This is reference material, not advice. Always confirm with a US CPA
before acting on it. Tax law changes; pack version is v1 dated 2026-06.

## Entity Classification

The IRS does not have a single "LLC" tax classification. By default, a
domestic LLC is classified for federal tax purposes based on the number
of members it has:

- **Single-member LLC** is treated as a **disregarded entity** by default.
  The LLC itself files no federal income tax return. Instead, its income
  and expenses are reported on the owner's return as if the LLC didn't
  exist. For Specific Edge Outsourcing LLC owned by AMZ Expert Global
  Limited (Hong Kong), the default is disregarded-entity treatment, which
  means the LLC's activities flow through to the foreign corporate owner.
- **Multi-member LLC** is treated as a **partnership** by default. The
  partnership files Form 1065 and issues K-1s to each member. This pack
  does not cover multi-member rules — engage a CPA if you add a second
  member.

An LLC can elect a different classification by filing **Form 8832**
(Entity Classification Election). The two common elections are:

- Elect to be treated as a **C corporation** by filing Form 8832 and then
  filing Form 1120 annually. The LLC becomes a separate taxable entity
  paying corporate income tax. Distributions to the foreign parent become
  dividends potentially subject to 30% US withholding (reducible by treaty).
- Elect to be treated as an **S corporation** by filing Form 2553. **This
  is NOT available** when any owner is a non-resident alien individual or
  a foreign corporation. A foreign-owned LLC cannot be an S corp.

The default disregarded-entity treatment is the most common choice for
foreign-owned LLCs because it avoids two layers of US tax (entity-level
and dividend withholding). But disregarded-entity treatment carries its
own consequence: the foreign owner may have a US federal income tax
filing obligation directly if the LLC generates US-source effectively
connected income (see "Federal Income Tax Basics" below).

For employment-tax purposes and certain excise taxes, a single-member
LLC is treated as a **separate entity** even when disregarded for income
tax. This means the LLC has its own EIN and files its own payroll
returns (Form 941, Form 940, etc.) when it has employees.

Always confirm with a CPA before electing corporate treatment. The
election is generally effective for five years and cannot be reversed
without IRS consent.

## Form 5472 + Pro Forma 1120

Form 5472 is the single biggest landmine for foreign-owned US LLCs. The
rules changed in 2017 to require any foreign-owned disregarded-entity
US LLC to file Form 5472 along with a pro forma Form 1120 even if the
LLC has no income tax to pay.

**Who must file.** Any domestic LLC that is wholly owned by one foreign
person (individual or entity) and that is treated as a disregarded
entity for federal income tax purposes. Specific Edge Outsourcing LLC,
owned 100% by AMZ Expert Global Limited (Hong Kong), falls squarely in
this category.

**What "reportable transactions" mean.** Almost any transaction between
the LLC and its foreign owner, or between the LLC and any party
related to the foreign owner, is a reportable transaction. This
includes:

- Capital contributions to the LLC from the foreign owner.
- Distributions from the LLC to the foreign owner.
- Loans between the LLC and the foreign owner (or any related party).
- Sales of services or property between the LLC and the foreign owner.
- Payments for the use of property (rent, royalties, license fees).
- Any other amount paid or received between the LLC and a related party.

The threshold is **zero dollars** — any reportable transaction in the
tax year triggers the filing. If the LLC merely has its initial capital
contribution from the foreign owner in its first year, that alone is a
reportable transaction.

**The penalty.** Failure to file Form 5472, or filing a substantially
incomplete Form 5472, triggers a **$25,000 penalty per form per year**.
The penalty is automatic and applied per missing or substantially
incomplete return. Continued failure after IRS notice triggers
additional $25,000 penalties. There is no de minimis exception.

**How it's filed.** A foreign-owned disregarded-entity LLC files Form
5472 attached to a pro forma Form 1120 (US Corporation Income Tax
Return). Only certain lines on the 1120 are required — name, address,
EIN, the box indicating it's being filed for a foreign-owned
disregarded entity, and the attached Form 5472. The pro forma 1120 is
not a full corporate return; it's a transmittal vehicle.

**Due date.** Form 5472 + pro forma 1120 is due **April 15** following
the close of the tax year (for calendar-year filers). A six-month
extension is available by filing **Form 7004** by the original due
date, pushing the deadline to October 15. The extension grants extra
time to file but not extra time to pay any tax — there is generally no
tax to pay for a disregarded-entity LLC, so the extension is purely
procedural.

**Filing method.** Foreign-owned disregarded-entity LLCs are required
to file Form 5472 by **paper or by fax** to the address specified in
the form instructions. The IRS does not currently accept e-filing for
this specific filing combination. Allow extra mail time and use
trackable shipping.

**Record-keeping.** The IRS requires that you maintain records
sufficient to establish the accuracy of the Form 5472 disclosures —
contracts, invoices, intercompany loan agreements, transfer-pricing
documentation, etc. Records must generally be retained for as long as
the assessment period remains open.

Always confirm Form 5472 due dates and reporting thresholds with a CPA
before filing. This is the most-penalized area for foreign-owned LLCs.

## Federal Income Tax Basics

Whether the LLC owes US federal income tax depends on two questions:
(1) is the income US-source, and (2) is the LLC engaged in a US trade
or business such that the income is effectively connected.

**US-source vs foreign-source income.** Source rules are statutory and
depend on the type of income. For services performed for US customers,
the source is generally where the services are performed, not where the
customer is located. Services performed entirely outside the US for US
customers are typically foreign-source. Services performed in the US
are typically US-source.

**Effectively Connected Income (ECI).** A foreign person who is
engaged in a US trade or business is taxed on income that is
effectively connected with that trade or business at the same
graduated rates that apply to US persons. ECI is reported on Form
1040-NR (for non-resident alien individuals) or Form 1120-F (for
foreign corporations).

For a foreign corporation owning a disregarded US LLC, the LLC's
activities are attributed to the foreign corporation. If the LLC's US
activities rise to the level of a US trade or business, the foreign
corporate owner has a Form 1120-F filing obligation for the ECI.

**When a services LLC creates a US trade or business.** This is a
facts-and-circumstances determination. Factors include: physical
presence of the LLC's owners or employees in the US, customer base
location, where the services are performed, whether there's a fixed
place of business in the US, and whether the foreign owner has
authority to conclude contracts in the US.

A US LLC owned by a foreign corporation that does nothing more than
hold investment assets — or that performs all services from outside
the US — generally does not have ECI. A US LLC with US-based employees
performing services for US clients generally does.

**Treaty considerations.** The US-Hong Kong treaty is **not in force**;
there is no income tax treaty between the US and Hong Kong as of this
writing. This means standard non-treaty rules apply to a Hong Kong
parent owning a US LLC: 30% withholding on US-source fixed,
determinable, annual, or periodic (FDAP) income such as dividends,
interest, royalties, and certain other passive income paid by the LLC
to the Hong Kong parent (or attributed to it under disregarded-entity
rules).

Always confirm with a CPA whether your specific activities create ECI
or US trade-or-business status. The "effectively connected" question
is the single most consequential US tax determination for a
foreign-owned LLC.

## State Tax Considerations

State tax rules are separate from federal and vary by state. The two
main areas for a foreign-owned US LLC are franchise tax (a tax for
the privilege of being formed or registered in the state) and income
tax (on income earned in or attributable to the state).

**Delaware franchise tax.** If the LLC is formed in Delaware (a common
formation state), the LLC owes the Delaware annual franchise tax of
**$300** flat per year, due by **June 1**. This is independent of
whether the LLC has any Delaware-source income or any business activity
in Delaware. Failure to pay triggers a $200 penalty plus 1.5%
interest per month.

**State income tax.** Most states impose income tax based on either
where the LLC is formed or where its business activities are located
(or both). A disregarded-entity LLC's income generally passes through
to the owner for state-tax purposes the same way it does for federal,
but state-level reporting requirements can differ — some states
require a state-level partnership or composite return even when the
federal classification is disregarded.

For a Hong Kong-owned disregarded US LLC with no US-state physical
presence, state income tax obligations are generally minimal but
fact-specific. States with no income tax (Texas, Florida, Nevada,
Wyoming, South Dakota, Washington, Tennessee, New Hampshire as
applicable) have no income tax exposure for LLCs formed or operating
there.

**Sales tax nexus brief.** US sales tax is administered by states (not
the federal government). For e-commerce sellers using Amazon as a
marketplace, **most states classify Amazon as a "marketplace
facilitator"** under post-2018 (Wayfair) economic nexus rules. This
means Amazon collects and remits sales tax on the seller's behalf for
sales made through the Amazon platform in those states. The seller's
own direct sales (not through a marketplace) are subject to standard
economic nexus thresholds — typically $100,000 in sales OR 200
transactions in a state per year, with each state's specific
thresholds varying.

For a services LLC (not e-commerce), sales tax is generally a non-issue
because most services are not taxable. Specific service categories —
digital products, software-as-a-service, telecom — have state-specific
taxability rules.

**Foreign qualification.** If the LLC formed in one state (say
Delaware) does business in another state (say California), it may need
to register as a "foreign LLC" in that second state and pay that
state's annual fees. "Doing business" is a state-by-state definition
typically based on physical presence, employees, property, or sustained
in-state activity.

Always confirm state-specific obligations with a CPA familiar with the
states where the LLC operates. State tax compliance is the area most
likely to be missed by foreign owners focused on federal compliance.

## Filing Calendar

Below is the annual calendar of US federal tax deadlines that apply to
a foreign-owned single-member US LLC treated as a disregarded entity
(calendar-year filer).

**January.** Form W-2 and Form 1099-NEC to recipients by **January 31**.
Form 1099-NEC also to IRS by January 31. Other 1099-series forms to
IRS by February 28 (paper) or March 31 (electronic).

**March.** No federal income tax filings specifically for a
disregarded-entity LLC. If the LLC has elected corporate treatment,
Form 1120-S (if S corp, not available for foreign-owned) would be due
March 15; Form 1065 (if multi-member partnership) also March 15.

**April.** **April 15** — primary federal filing deadline:
- Form 5472 + pro forma 1120 (the foreign-owned disregarded LLC filing).
- Form 1120-F (US Corporation Income Tax Return for Foreign
  Corporations) if the foreign parent has ECI attributable to US
  business activities.
- Form 1040-NR (US Nonresident Alien Income Tax Return) if a foreign
  individual owner has US ECI.
- Form 7004 (six-month extension) must be filed by April 15 to extend
  any of the above to October 15.

**June.** **June 1** — Delaware annual franchise tax ($300) due if the
LLC is Delaware-formed. **June 15** — second-quarter estimated tax
payment (if applicable for an elected corporate entity).

**October.** **October 15** — extended due date for Form 5472 + pro
forma 1120, Form 1120-F, and Form 1040-NR if Form 7004 was filed by
April 15.

**Other dates.** Annual report dates vary by state of formation —
Delaware, Wyoming, Texas, Florida, and others each have their own
schedules. The state of formation typically sends an annual report
reminder. Some states (e.g. California) have annual minimum franchise
taxes that are due regardless of income.

**Quarterly federal payroll deposits.** If the LLC has employees,
Form 941 (Employer's Quarterly Federal Tax Return) is due by the last
day of the month following the end of each quarter (April 30, July 31,
October 31, January 31). Form 940 (Federal Unemployment Tax) is due
January 31 annually.

Always confirm calendar dates with a CPA — IRS deadlines occasionally
shift when April 15 falls on a weekend or holiday, and Emancipation Day
in Washington DC can push the deadline by a business day.

## EIN / ITIN / SSN

US tax filings require a tax identification number. There are three
types: EIN (for entities), SSN (for US citizens and authorized
residents), and ITIN (for individuals who need a tax ID but are not
eligible for an SSN).

**EIN — Employer Identification Number.** Every US LLC needs an EIN.
The EIN is the LLC's federal tax identification number, used on all
filings (Form 5472, payroll returns, business bank account
applications, etc.). An EIN is obtained by filing **Form SS-4** with
the IRS. For a foreign-owned LLC where no responsible party has an
SSN or ITIN, the SS-4 cannot be filed online — it must be filed by
fax or by mail. The IRS typically processes a fax SS-4 within
4–6 weeks; mail takes longer. The form must list a "responsible
party" with their taxpayer identification number (TIN); for foreign
owners without a US TIN, write "Foreign" in the TIN field.

**ITIN — Individual Taxpayer Identification Number.** An ITIN is
required for non-resident foreign individuals who must file a US tax
return (e.g. owners of pass-through entities with US ECI) but do not
qualify for an SSN. ITINs are obtained by filing **Form W-7** along
with the tax return that requires the ITIN. Original supporting
documents (passport) or certified copies must accompany the
application. ITINs can take 7–11 weeks to process and must be renewed
every several years if not used.

**SSN — Social Security Number.** SSNs are issued to US citizens and
authorized workers in the US. A foreign owner of a US LLC who is not
otherwise present and working in the US generally does not have or
need an SSN.

**Practical recommendation.** For a Hong Kong corporate owner of a
single-member US LLC, the typical sequence is:

1. Form the LLC in the state of formation.
2. File Form SS-4 to obtain the LLC's EIN. Use the LLC's address and
   list the foreign corporate parent as the responsible party, writing
   "Foreign" for the responsible party's TIN.
3. The foreign parent does not typically need its own US TIN unless it
   has its own US ECI requiring a Form 1120-F.
4. If the individual director or owner needs to be on the US filings
   (e.g. as signer), they generally do not need their own US TIN
   unless they personally have US tax obligations.

Always confirm with a CPA which TINs you need before applying. ITIN
applications in particular have strict documentation rules and are
frequently rejected for paperwork errors.

## Withholding Obligations

When a US person (including a US LLC) pays certain types of US-source
income to a foreign person, the US payer must withhold tax and remit
it to the IRS. The rules are codified in IRC sections 1441 through
1446 and apply to "fixed, determinable, annual, or periodic" (FDAP)
income paid to foreign persons.

**The 30% default rate.** The statutory withholding rate on US-source
FDAP income paid to a foreign person is **30%**. This applies to
dividends, interest, royalties, rents, and certain other passive
income.

**Treaty rate reductions.** A US tax treaty with the recipient's
country of residence can reduce the withholding rate (often to 5%,
10%, or 15% depending on the income type). For Hong Kong, **no US-Hong
Kong income tax treaty is in force**, so the standard 30% rate applies
to FDAP income paid by a US LLC to its Hong Kong parent.

**Form 1042 and Form 1042-S.** When a US payer makes payments subject
to withholding to a foreign person, two annual filings are required:

- **Form 1042** — Annual Withholding Tax Return for US Source Income
  of Foreign Persons. Filed by the withholding agent (the US LLC).
  Due **March 15** following the close of the calendar year. Reports
  total withholding and remits it to the IRS.
- **Form 1042-S** — Foreign Person's US Source Income Subject to
  Withholding. One Form 1042-S per recipient (per income type).
  Furnished to the recipient and filed with the IRS by **March 15**.

Failure to file or to deposit withheld amounts on time triggers
penalties similar to the payroll-tax penalties (multi-tier based on
how late the deposit is).

**Intercompany services.** Payments by a US LLC to its foreign parent
for genuine services performed by the parent outside the US for the
benefit of the US LLC are generally treated as foreign-source income
and not subject to US withholding. However, the services must be
genuinely performed outside the US, documented (intercompany services
agreement, invoices), and at arm's-length transfer-pricing rates.

**Intercompany loans.** Interest paid by the US LLC to a foreign
parent on intercompany loans is generally US-source FDAP income
subject to 30% withholding. The "portfolio interest exemption" — a
common 0% rate for foreign lenders on US-source interest — generally
does **not** apply to interest paid to a related foreign person who
holds 10% or more of the borrower.

**Contractor payments to non-US individuals.** Payments by a US LLC
to non-US individuals who perform services entirely outside the US
are generally foreign-source and not subject to withholding. The
LLC should obtain a properly-completed **Form W-8BEN** from the
contractor to document foreign status and avoid presumption rules.

Always confirm withholding obligations with a CPA before making
intercompany payments. Misapplied withholding (either over-withholding
or under-withholding) creates IRS exposure and is hard to fix
retroactively.

## Contractor vs Employee Classification

US payroll and tax obligations differ dramatically depending on
whether a worker is classified as an employee or an independent
contractor. Misclassification is one of the most-audited areas for
small businesses and can trigger back taxes, penalties, and interest
going back several years.

**Employees** receive a **Form W-2** at year-end. The employer is
required to:

- Withhold federal income tax based on the employee's Form W-4.
- Withhold and pay the employee's share of Social Security and Medicare
  (FICA) taxes — 7.65% withheld from the employee plus 7.65% paid by
  the employer.
- Pay federal unemployment tax (FUTA) of 0.6% on the first $7,000 of
  wages per employee per year.
- Pay state unemployment tax (SUTA), worker's compensation insurance
  premiums, and any state-mandated benefits.
- File Form 941 quarterly, Form 940 annually, Form W-2 by January 31.

**Independent contractors** receive a **Form 1099-NEC** at year-end if
total payments to them are $600 or more in the tax year. The payer is
generally NOT required to withhold income tax or pay employment taxes.
The contractor is responsible for their own self-employment tax and
income tax.

**The IRS classification factors.** The IRS uses a "facts and
circumstances" test based on three categories:

1. **Behavioral control** — does the payer direct how the work is done
   (instructions, training, evaluation systems)? If yes, more like an
   employee.
2. **Financial control** — does the worker have a significant
   investment in their own tools/equipment, can incur losses,
   provides services to other clients, is paid on a project basis
   (rather than a salary)? If yes, more like a contractor.
3. **Type of relationship** — is there a written contract describing
   the relationship as independent? Are there employee-type benefits
   (health insurance, pension, paid vacation)? Is the relationship
   expected to continue indefinitely or for a specific project?

No single factor is decisive. The IRS looks at the whole picture.

**Why misclassification is expensive.** If the IRS reclassifies a
contractor as an employee, the employer can owe:

- Back employment taxes (employer and employee FICA, FUTA).
- Income tax that should have been withheld.
- Penalties — typically 1.5% of wages for unwithheld income tax, 20%
  of the employee FICA share, plus failure-to-file and
  failure-to-deposit penalties.
- Interest from the original due date.
- Potential state-level penalties on top.

These add up fast. A misclassified worker earning $80,000/year for
three years can generate $30,000+ in penalties alone.

**Practical recommendation for a services LLC.** If the LLC is paying
non-US contractors performing services outside the US, the
contractor-employee distinction is generally less risky because the
US payroll obligations don't apply to foreign workers performing
services entirely abroad. But document the relationship: written
agreement, contractor invoices, Form W-8BEN on file. If any work is
performed inside the US, or if a contractor is based in the US, get a
US payroll specialist involved before the first payment.

Always confirm contractor vs employee classification with a CPA or
payroll specialist before signing the first paycheck. Reclassification
audits are common and expensive.

## Common Penalty Triggers

This section summarizes the audit and penalty patterns most likely to
affect a foreign-owned US LLC. Understanding what triggers IRS
attention is the cheapest form of compliance.

**Late or missing Form 5472.** The single most common and most
expensive penalty for foreign-owned LLCs. Automatic $25,000 per
missed or substantially incomplete form. There is no de minimis
exception. The IRS knows when a foreign-owned LLC exists (via the
SS-4 application that lists the foreign responsible party) and will
flag missing 5472s.

**Undisclosed foreign accounts.** A US LLC that has signature
authority or beneficial ownership of foreign financial accounts (bank
accounts, brokerage accounts) over $10,000 in aggregate at any point
during the year must file:

- **FBAR (FinCEN Form 114)** annually by **April 15** (automatic
  extension to October 15 — no separate extension form required).
  Penalty for willful failure to file: greater of $100,000 or 50% of
  the account balance. Non-willful: up to $10,000 per violation.
- **Form 8938 (FATCA — Statement of Specified Foreign Financial
  Assets)** filed with the federal income tax return when applicable
  thresholds are exceeded (the thresholds for entities are higher
  than for individuals but still relatively low).

A US LLC owned by a Hong Kong parent generally has only US bank
accounts and does not have FBAR exposure at the LLC level, but
intercompany loans or operational accounts in Hong Kong held in the
LLC's name could trigger reporting.

**ECI mischaracterization.** Treating effectively connected income as
foreign-source income to avoid federal tax. The IRS scrutinizes this
particularly when a foreign-owned LLC has US employees, US customers,
US-based contracts, or any US fixed place of business. Getting this
wrong creates exposure to back tax (at graduated rates plus 30%
branch profits tax for foreign corporate owners), penalties (20% of
underpayment for substantial understatement, up to 75% for fraud),
and interest.

**Payroll tax delinquency.** Among the most aggressively-pursued IRS
collection actions. Unpaid trust fund taxes (employee FICA and
withheld income tax) can be personally assessed against responsible
persons under the Trust Fund Recovery Penalty (TFRP) — a 100% personal
penalty equal to the unpaid trust-fund portion. A foreign corporate
owner of a US LLC with US employees should ensure payroll deposits
are made on schedule and never used as working capital.

**Transfer pricing misalignment.** Intercompany transactions between
the US LLC and its foreign parent must be at arm's-length prices.
Charges to or from the parent that are not at arm's length can be
recharacterized by the IRS, triggering back tax, transfer pricing
penalties (20% or 40% of the adjustment depending on materiality),
and adjustments to multi-year filings. Maintain documentation:
intercompany services agreement, contemporaneous transfer-pricing
study (or at minimum a documented methodology), invoices supporting
each charge.

**Late-filed information returns.** Form 1099-NEC, Form 1042-S, Form
8804/8805 (if a partnership with foreign partners — not applicable
to single-member LLCs but mentioned for completeness). Late-filed
information returns trigger graduated penalties starting around $60
per return for short delays, scaling to $310+ per return for delays
beyond August 1, and substantially higher penalties for intentional
disregard.

**State franchise tax delinquency.** Less aggressively pursued by
states than the IRS pursues federal taxes, but a delinquent state
franchise tax can lead to administrative dissolution of the LLC,
which complicates banking, contracts, and the LLC's legal capacity
to operate.

**Practical mitigation.** The single most effective penalty avoidance
strategy is calendaring. Put every applicable due date in a system
that fires reminders 30 and 7 days in advance. Engage a US CPA at
formation and review filings annually before submission. Maintain
clean intercompany documentation contemporaneously, not at year-end
when memory and discipline both fade.

Always confirm with a US CPA when uncertain. The cost of a CPA
consultation is trivial compared to the cost of any single penalty
in this list.

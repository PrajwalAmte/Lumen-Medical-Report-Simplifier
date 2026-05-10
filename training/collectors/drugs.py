"""
Indian drug data collector.

Two data sources:
  1. Jan Aushadhi formulary — hardcoded from PMBJP published list (high quality,
     India-specific, covers generic brands, pricing, Jan Aushadhi store availability).
  2. OpenFDA drug labels — fetches prescribing info for the same drugs
     (mechanism, warnings, interactions) to enrich training text.

No scraping required — Jan Aushadhi data is manually curated from the public
formulary, OpenFDA is a clean REST API.

Output per record:
    {"text": "...", "source": "jan_aushadhi|openfda", "drug": "..."}
"""

import time
from pathlib import Path

import requests

from .utils import append_jsonl

OPENFDA_BASE = "https://api.fda.gov/drug/label.json"

# ---------------------------------------------------------------------------
# Jan Aushadhi formulary — curated from PMBJP public product list.
# Format: generic_name, category, brand_examples (Indian market),
#         indication + mechanism (DAPT text), MRP vs Jan Aushadhi price.
# Source: janaushadhi.gov.in / PMBJP Product List
# ---------------------------------------------------------------------------
JAN_AUSHADHI_ENTRIES = [
    {
        "generic_name": "Metformin Hydrochloride 500mg",
        "category": "Anti-Diabetic — Biguanide",
        "indian_brands": "Glycomet (USV), Glucophage (Merck), Obimet (Systopic)",
        "jan_aushadhi_price_inr": 0.50,
        "market_mrp_inr": 2.50,
        "text": (
            "Metformin Hydrochloride 500mg is the first-line oral anti-diabetic drug for "
            "Type 2 diabetes mellitus in India, recommended by all major Indian guidelines "
            "including RSSDI and API. It is a biguanide that reduces hepatic glucose production "
            "(gluconeogenesis), improves peripheral insulin sensitivity, and does not cause "
            "hypoglycaemia or weight gain. Commonly prescribed as Glycomet by USV, Glucophage "
            "by Merck, or Obimet by Systopic. Available at Jan Aushadhi stores at ₹0.50/tablet "
            "versus branded MRP of ₹2.50/tablet — a significant saving for long-term diabetic "
            "patients. Side effects include nausea, diarrhoea, and rarely lactic acidosis in "
            "renal impairment. Contraindicated in eGFR < 30 mL/min. Widely used across all "
            "socioeconomic strata in India due to availability and low cost."
        ),
    },
    {
        "generic_name": "Atorvastatin Calcium 10mg",
        "category": "Cardiovascular — HMG-CoA Reductase Inhibitor (Statin)",
        "indian_brands": "Atorva (Cadila), Lipitor (Pfizer), Tonact (Lupin), Aztor (Sun Pharma)",
        "jan_aushadhi_price_inr": 1.20,
        "market_mrp_inr": 8.00,
        "text": (
            "Atorvastatin 10mg is the most widely prescribed statin in India for "
            "dyslipidaemia and cardiovascular risk reduction. It is an HMG-CoA reductase "
            "inhibitor that reduces LDL cholesterol synthesis in the liver. Available as "
            "Atorva by Cadila, Tonact by Lupin, Aztor by Sun Pharma. Lipid Profile tests "
            "showing LDL > 130 mg/dL in high-risk Indian patients (diabetics, hypertensives) "
            "typically warrant statin initiation per ICMR guidelines. Jan Aushadhi price is "
            "₹1.20/tablet vs branded MRP of ₹8.00/tablet. Side effects include myalgia, "
            "elevated liver enzymes. Dose ranges 10–80mg daily. Evening dosing preferred. "
            "Must be distinguished from Rosuvastatin (Rozavel, Crestor) which is more potent "
            "at equivalent doses."
        ),
    },
    {
        "generic_name": "Amlodipine Besylate 5mg",
        "category": "Antihypertensive — Calcium Channel Blocker (CCB)",
        "indian_brands": "Amlokind (Mankind), Amcard (Nicholas), Norvasc (Pfizer)",
        "jan_aushadhi_price_inr": 0.80,
        "market_mrp_inr": 5.50,
        "text": (
            "Amlodipine 5mg is one of the most prescribed antihypertensive drugs in India. "
            "It is a long-acting dihydropyridine calcium channel blocker that relaxes vascular "
            "smooth muscle by blocking L-type calcium channels. Duration of action 24 hours — "
            "once-daily dosing. Used for hypertension and stable angina. Available as Amlokind "
            "by Mankind, Amcard by Nicholas Piramal. Jan Aushadhi price ₹0.80/tablet vs MRP "
            "₹5.50. Common side effects: pedal oedema (ankle swelling), flushing, headache. "
            "Safe in diabetics and CKD patients. Often combined with telmisartan (Telma-AM) or "
            "atenolol (Amlopress-AT) as fixed-dose combinations widely available in India."
        ),
    },
    {
        "generic_name": "Telmisartan 40mg",
        "category": "Antihypertensive — Angiotensin II Receptor Blocker (ARB)",
        "indian_brands": "Telma (Glenmark), Telmikind (Mankind), Telvas (Emcure)",
        "jan_aushadhi_price_inr": 2.00,
        "market_mrp_inr": 9.00,
        "text": (
            "Telmisartan 40mg is an ARB widely used in India for hypertension, heart failure, "
            "and diabetic nephropathy. It blocks the angiotensin II type 1 receptor (AT1), "
            "reducing vasoconstriction and aldosterone secretion. Preferred over ACE inhibitors "
            "in Indian patients who develop dry cough with ACEi (common in South Asian genetics). "
            "Also has PPAR-gamma agonist activity offering metabolic benefits in diabetics. "
            "Available as Telma (Glenmark), Telmikind (Mankind). Jan Aushadhi price ₹2.00 vs "
            "MRP ₹9.00. Safe in CKD with monitoring of creatinine and potassium."
        ),
    },
    {
        "generic_name": "Omeprazole 20mg",
        "category": "Gastrointestinal — Proton Pump Inhibitor (PPI)",
        "indian_brands": "Omez (Dr. Reddy's), Ocid (Cipla), Prilosec (AstraZeneca India)",
        "jan_aushadhi_price_inr": 0.70,
        "market_mrp_inr": 6.00,
        "text": (
            "Omeprazole 20mg is a proton pump inhibitor (PPI) widely prescribed in India for "
            "peptic ulcer disease, GERD (gastroesophageal reflux), and as gastroprotection with "
            "NSAIDs. It irreversibly inhibits the H+/K+-ATPase enzyme (proton pump) in gastric "
            "parietal cells. Available as Omez by Dr. Reddy's, Ocid by Cipla. Jan Aushadhi "
            "₹0.70/capsule vs MRP ₹6.00. Long-term use risks: hypomagnesaemia, vitamin B12 "
            "deficiency, C. difficile infection, fracture risk. Often over-prescribed in India — "
            "should not routinely be used without indication. Pantoprazole (Pan 40) and "
            "Rabeprazole (Razo) are alternatives."
        ),
    },
    {
        "generic_name": "Azithromycin 500mg",
        "category": "Antibiotic — Macrolide",
        "indian_brands": "Azithral (Alembic), Zithromax (Pfizer), Azee (Cipla)",
        "jan_aushadhi_price_inr": 3.50,
        "market_mrp_inr": 15.00,
        "text": (
            "Azithromycin 500mg is a macrolide antibiotic extensively used in India for "
            "community-acquired pneumonia, pharyngitis, enteric fever (typhoid), and "
            "sexually transmitted infections. It inhibits bacterial protein synthesis by "
            "binding to the 50S ribosomal subunit. Unique long intracellular half-life allows "
            "once-daily dosing and short 3–5 day courses. Available as Azithral (Alembic), "
            "Azee (Cipla). Jan Aushadhi ₹3.50 vs MRP ₹15.00. Rising azithromycin resistance in "
            "India reported by ICMR AMR surveillance — should be used judiciously. Not for viral "
            "infections. QT prolongation risk — avoid with other QT-prolonging drugs."
        ),
    },
    {
        "generic_name": "Ciprofloxacin Hydrochloride 500mg",
        "category": "Antibiotic — Fluoroquinolone",
        "indian_brands": "Ciplox (Cipla), Cifran (Ranbaxy), Zoxan (FDC)",
        "jan_aushadhi_price_inr": 2.00,
        "market_mrp_inr": 8.50,
        "text": (
            "Ciprofloxacin 500mg is a fluoroquinolone antibiotic used in India for urinary "
            "tract infections, bacterial diarrhoea, typhoid fever, and respiratory infections. "
            "Inhibits DNA gyrase and topoisomerase IV. Available as Ciplox (Cipla), Cifran "
            "(Ranbaxy). Jan Aushadhi ₹2.00 vs MRP ₹8.50. High fluoroquinolone resistance rates "
            "in India, especially E. coli in UTI — urine culture must guide therapy. Avoided in "
            "children due to cartilage toxicity. Avoid in pregnancy. Drug interactions with "
            "antacids (chelation), theophylline, warfarin."
        ),
    },
    {
        "generic_name": "Amoxicillin Trihydrate 500mg",
        "category": "Antibiotic — Aminopenicillin",
        "indian_brands": "Mox (Ranbaxy), Novamox (Cipla), Wymox (Wyeth India)",
        "jan_aushadhi_price_inr": 1.50,
        "market_mrp_inr": 7.00,
        "text": (
            "Amoxicillin 500mg is a broad-spectrum penicillin antibiotic commonly used in India "
            "for respiratory tract infections, otitis media, skin infections, and H. pylori "
            "eradication (as part of triple therapy with clarithromycin and omeprazole). "
            "Available as Mox (Ranbaxy), Novamox (Cipla). Jan Aushadhi ₹1.50 vs MRP ₹7.00. "
            "Amoxicillin-clavulanate (Augmentin, Clavam) used for resistant organisms. "
            "Allergy risk in 1–10% — cross-reaction with other penicillins. Not effective "
            "against beta-lactamase-producing organisms without clavulanate."
        ),
    },
    {
        "generic_name": "Paracetamol (Acetaminophen) 500mg",
        "category": "Analgesic — Antipyretic",
        "indian_brands": "Calpol (GSK India), Dolo-650 (Micro Labs), Crocin (GSK)",
        "jan_aushadhi_price_inr": 0.30,
        "market_mrp_inr": 2.00,
        "text": (
            "Paracetamol 500mg is the most widely consumed OTC analgesic and antipyretic in India, "
            "used for fever, headache, and mild-to-moderate pain. Dolo-650 (Micro Labs 650mg) "
            "became one of India's best-selling tablets during COVID-19 pandemic. Mechanism: "
            "inhibits prostaglandin synthesis centrally. Jan Aushadhi ₹0.30/tablet vs MRP "
            "₹2.00. Safe at recommended doses but hepatotoxic in overdose — maximum 4g/day in "
            "adults, 2g/day in alcoholics or liver disease. Many Indian fixed-dose combinations "
            "contain paracetamol (Combiflam, Sumo, Flexon) — patients must account for total dose. "
            "Different from ibuprofen (Brufen, Combiflam) which is an NSAID with anti-inflammatory action."
        ),
    },
    {
        "generic_name": "Levothyroxine Sodium 50mcg",
        "category": "Thyroid Hormone Replacement",
        "indian_brands": "Thyronorm (Abbott India), Eltroxin (GSK), Thyrox (Macleods)",
        "jan_aushadhi_price_inr": 0.80,
        "market_mrp_inr": 4.50,
        "text": (
            "Levothyroxine 50mcg is the standard treatment for hypothyroidism in India. India "
            "has one of the world's highest burdens of thyroid disorders, with approximately "
            "42 million Indians affected. Hypothyroidism is diagnosed when TSH > 4.5 mIU/L with "
            "low Free T4. Levothyroxine is synthetic T4 that undergoes peripheral deiodination "
            "to active T3. Available as Thyronorm (Abbott), Eltroxin (GSK). Jan Aushadhi ₹0.80 "
            "vs MRP ₹4.50. Must be taken fasting, 30–60 min before breakfast. TSH target: "
            "0.5–2.5 mIU/L for most patients, 0.1–1.0 for pregnant women. Check TSH every "
            "6–8 weeks after dose change. Interactions: calcium, iron, antacids reduce absorption."
        ),
    },
    {
        "generic_name": "Clopidogrel Bisulfate 75mg",
        "category": "Antiplatelet — P2Y12 Inhibitor",
        "indian_brands": "Clopilet (Sun Pharma), Deplatt (Torrent), Plavix (Sanofi)",
        "jan_aushadhi_price_inr": 2.50,
        "market_mrp_inr": 12.00,
        "text": (
            "Clopidogrel 75mg is an antiplatelet agent widely used in India after percutaneous "
            "coronary intervention (PTCA/stent), acute MI, and stroke prevention. It irreversibly "
            "blocks the platelet ADP receptor P2Y12, inhibiting platelet aggregation. Available as "
            "Clopilet (Sun Pharma), Deplatt (Torrent). Jan Aushadhi ₹2.50 vs MRP ₹12.00. "
            "Often combined with aspirin (dual antiplatelet therapy — DAPT) post-stent. "
            "Risk: bleeding — check for signs of GI bleed, bruising. CYP2C19 polymorphism "
            "prevalent in Indian population may reduce efficacy — genetic testing sometimes done. "
            "Do not stop without cardiologist advice — risk of stent thrombosis."
        ),
    },
    {
        "generic_name": "Rosuvastatin Calcium 10mg",
        "category": "Cardiovascular — HMG-CoA Reductase Inhibitor (High-Intensity Statin)",
        "indian_brands": "Rozavel (Sun Pharma), Rosuvas (Cipla), Crestor (AstraZeneca)",
        "jan_aushadhi_price_inr": 2.00,
        "market_mrp_inr": 12.00,
        "text": (
            "Rosuvastatin 10mg is a high-intensity statin used in India for severe "
            "dyslipidaemia and high cardiovascular risk patients. More potent than atorvastatin: "
            "rosuvastatin 10mg ≈ atorvastatin 20mg for LDL reduction. Minimal hepatic metabolism "
            "(not via CYP3A4) — fewer drug interactions than atorvastatin. Available as Rozavel "
            "(Sun Pharma), Rosuvas (Cipla). Jan Aushadhi ₹2.00 vs MRP ₹12.00. "
            "Preferred in patients on CYP3A4-heavy regimens. Can cause myopathy — monitor CK. "
            "Must not be confused with atorvastatin at equivalent doses.</p>"
        ),
    },
    {
        "generic_name": "Glimepiride 2mg",
        "category": "Anti-Diabetic — Second Generation Sulphonylurea",
        "indian_brands": "Amaryl (Sanofi), Glimestar (Mankind), Glimy (FDC)",
        "jan_aushadhi_price_inr": 1.50,
        "market_mrp_inr": 8.00,
        "text": (
            "Glimepiride 2mg is a sulphonylurea used in India as second-line or add-on therapy "
            "for Type 2 diabetes when metformin alone is insufficient. Stimulates insulin "
            "secretion from pancreatic beta cells by blocking ATP-sensitive K+ channels. "
            "Available as Amaryl (Sanofi), Glimestar (Mankind). Jan Aushadhi ₹1.50 vs MRP ₹8.00. "
            "Risk of hypoglycaemia — patients must monitor blood glucose and not skip meals. "
            "Often combined with metformin (Glizid-M, Amaryl-M fixed-dose combinations). "
            "HbA1c target in Indian diabetics per RSSDI: < 7% for most, < 8% for elderly."
        ),
    },
    {
        "generic_name": "Pantoprazole Sodium 40mg",
        "category": "Gastrointestinal — Proton Pump Inhibitor (PPI)",
        "indian_brands": "Pan 40 (Alkem), Pantodac (Zydus), Pantop (Aristo)",
        "jan_aushadhi_price_inr": 1.00,
        "market_mrp_inr": 7.00,
        "text": (
            "Pantoprazole 40mg is widely used in India for GERD, peptic ulcer disease, and "
            "gastroprotection with NSAIDs or steroids. Pan 40 (Alkem) is among India's "
            "top-selling prescription drugs. It is a PPI that irreversibly binds the H+/K+-ATPase "
            "proton pump. Compared to omeprazole: more acid-stable, fewer drug interactions "
            "(does not significantly inhibit CYP2C19). Jan Aushadhi ₹1.00 vs MRP ₹7.00. "
            "See omeprazole for general PPI cautions."
        ),
    },
    {
        "generic_name": "Montelukast Sodium 10mg",
        "category": "Antiasthmatic — Leukotriene Receptor Antagonist",
        "indian_brands": "Montair (Cipla), Singulair (MSD), Montec (FDC)",
        "jan_aushadhi_price_inr": 2.50,
        "market_mrp_inr": 10.00,
        "text": (
            "Montelukast 10mg is used in India for allergic asthma, exercise-induced "
            "bronchoconstriction, and allergic rhinitis. It is a selective cysteinyl leukotriene "
            "CysLT1 receptor antagonist — reduces bronchospasm, mucus secretion, and airway "
            "inflammation. Available as Montair (Cipla), Singulair (MSD). Evening dosing "
            "preferred for asthma. Jan Aushadhi ₹2.50 vs MRP ₹10.00. Often combined with "
            "levocetrizine (Montair-LC) for allergic rhinitis — one of India's best-selling "
            "combination tablets. Neuropsychiatric adverse effects (mood changes, nightmares) "
            "reported — FDA warning issued in 2020."
        ),
    },
    {
        "generic_name": "Cetirizine Hydrochloride 10mg",
        "category": "Antihistamine — Second Generation",
        "indian_brands": "Cetzine (GSK), Zyrtec (UCB), Alerid (Cipla)",
        "jan_aushadhi_price_inr": 0.50,
        "market_mrp_inr": 3.00,
        "text": (
            "Cetirizine 10mg is a second-generation H1 antihistamine widely used in India for "
            "allergic rhinitis, urticaria (hives), and other allergic disorders. Less sedating "
            "than first-generation antihistamines like chlorphenamine (Cadistin) or "
            "promethazine (Phenergan). Available as Cetzine (GSK), Alerid (Cipla). Jan Aushadhi "
            "₹0.50 vs MRP ₹3.00. Once-daily dosing. May cause mild drowsiness — caution during "
            "driving. Levocetirizine (Xyzal, Levocet) is the active enantiomer, slightly more "
            "potent at lower doses."
        ),
    },
    {
        "generic_name": "Ferrous Sulfate 200mg (65mg elemental iron)",
        "category": "Haematinic — Iron Supplement",
        "indian_brands": "Fersolate (Wallace), Autrin (Wyeth), Orofer (Emcure)",
        "jan_aushadhi_price_inr": 0.40,
        "market_mrp_inr": 2.00,
        "text": (
            "Ferrous Sulfate 200mg providing 65mg elemental iron is the standard treatment for "
            "iron deficiency anaemia in India. India has the world's highest burden of iron "
            "deficiency anaemia — 53% of women of reproductive age are anaemic (NFHS-5). "
            "Haemoglobin < 11g/dL in women and < 13g/dL in men with microcytic hypochromic "
            "picture and low serum ferritin. Take on empty stomach or with Vitamin C for better "
            "absorption. Jan Aushadhi ₹0.40 vs MRP ₹2.00. Side effects: black stool (normal), "
            "constipation, nausea. Avoid with antacids, tea, or calcium-rich foods that impair "
            "absorption. IV iron (Monofer, Injectafer) used for severe cases or oral intolerance."
        ),
    },
    {
        "generic_name": "Cholecalciferol (Vitamin D3) 60,000 IU capsule",
        "category": "Vitamins — Fat-Soluble",
        "indian_brands": "Calcirol (Cadila), D-Rise (USV), Uprise-D3 (Eris)",
        "jan_aushadhi_price_inr": 5.00,
        "market_mrp_inr": 35.00,
        "text": (
            "Vitamin D3 60,000 IU weekly pulsed dosing is the standard Indian protocol for "
            "Vitamin D deficiency (25-OH Vitamin D < 20 ng/mL). Vitamin D deficiency is "
            "epidemic in India — 70–90% of the population is deficient despite abundant sunlight, "
            "due to indoor lifestyles, skin pigmentation, and vegetarian diet. Deficiency causes "
            "rickets in children, osteomalacia and muscle weakness in adults, and is linked to "
            "diabetes, hypothyroidism, and recurrent infections. Typical regimen: 60,000 IU "
            "weekly for 8–12 weeks, then monthly maintenance. Jan Aushadhi ₹5.00 vs MRP ₹35.00. "
            "Calcirol (Cadila) is the most prescribed brand. Toxicity risk at > 10,000 IU/day "
            "long-term — monitor serum calcium."
        ),
    },
    {
        "generic_name": "Folic Acid 5mg",
        "category": "Haematinic — Vitamin B9",
        "indian_brands": "Folvite (Pfizer India), Folicap (Sun Pharma)",
        "jan_aushadhi_price_inr": 0.30,
        "market_mrp_inr": 1.50,
        "text": (
            "Folic Acid 5mg is prescribed in India for megaloblastic anaemia, as periconceptional "
            "supplementation (next steps recommendation before and during early pregnancy to prevent "
            "neural tube defects), and with methotrexate to prevent toxicity. Essential for DNA "
            "synthesis and red blood cell maturation. Deficiency causes macrocytic anaemia — MCV "
            "> 100 fL, hypersegmented neutrophils on peripheral smear. Different from B12 "
            "deficiency (both cause macrocytic anaemia — must distinguish). Jan Aushadhi ₹0.30 "
            "vs MRP ₹1.50. Government of India's National Iron Plus Initiative includes folic "
            "acid supplementation for adolescents."
        ),
    },
    {
        "generic_name": "Calcium Carbonate 500mg + Vitamin D3 250 IU",
        "category": "Minerals and Vitamins — Bone Health",
        "indian_brands": "Shelcal (Elder Pharma), Calcimax (Meyer Organics), Macalvit (Macleods)",
        "jan_aushadhi_price_inr": 2.00,
        "market_mrp_inr": 10.00,
        "text": (
            "Calcium Carbonate 500mg + Vitamin D3 combination is widely prescribed in India "
            "for osteoporosis prevention, post-menopausal bone health, and calcium deficiency. "
            "Indian vegetarian diets are often low in bioavailable calcium. Shelcal (Elder Pharma) "
            "is the most prescribed brand. Jan Aushadhi ₹2.00 vs MRP ₹10.00. Calcium carbonate "
            "requires gastric acid for absorption — take with meals. Calcium citrate does not "
            "require acid — better for patients on PPIs. Total daily calcium intake should not "
            "exceed 2000mg from all sources — excess linked to cardiovascular risk in some studies."
        ),
    },
    {
        "generic_name": "Metronidazole 400mg",
        "category": "Antibiotic/Antiprotozoal — Nitroimidazole",
        "indian_brands": "Flagyl (Sanofi India), Metrogyl (JB Chemicals), Aristogyl (Aristo)",
        "jan_aushadhi_price_inr": 0.80,
        "market_mrp_inr": 4.00,
        "text": (
            "Metronidazole 400mg is a nitroimidazole antiprotozoal widely used in India for "
            "amoebiasis (Entamoeba histolytica — extremely common in India), Giardia lamblia, "
            "Trichomonas vaginalis, and anaerobic bacterial infections. Also used in H. pylori "
            "eradication regimens. India's tropical climate and water quality make protozoal "
            "infections very common. Available as Flagyl (Sanofi India), Metrogyl (JB Chemicals). "
            "Jan Aushadhi ₹0.80 vs MRP ₹4.00. Disulfiram-like reaction with alcohol — absolute "
            "contraindication. Metallic taste common. Peripheral neuropathy with prolonged use."
        ),
    },
    {
        "generic_name": "Hydroxychloroquine Sulfate 200mg",
        "category": "Antimalarial / Disease-Modifying Antirheumatic Drug (DMARD)",
        "indian_brands": "HCQs (Cipla), Dolquine (Zuventus), Plaquenil (Sanofi)",
        "jan_aushadhi_price_inr": 3.00,
        "market_mrp_inr": 14.00,
        "text": (
            "Hydroxychloroquine 200mg (HCQ) is used in India for malaria prophylaxis and "
            "treatment, and as a DMARD for rheumatoid arthritis and SLE (systemic lupus "
            "erythematosus). Also used as an add-on in Type 2 diabetes in India (HCQs by Cipla "
            "approved for this by DCGI). Mechanism: disrupts lysosomal pH in parasites, "
            "anti-inflammatory in autoimmune conditions. Jan Aushadhi ₹3.00 vs MRP ₹14.00. "
            "Retinopathy risk with long-term use — annual ophthalmology review required. "
            "QT prolongation risk at higher doses. Famous for widespread use during COVID-19."
        ),
    },
    {
        "generic_name": "Enalapril Maleate 5mg",
        "category": "Antihypertensive — ACE Inhibitor",
        "indian_brands": "Enam (Emcure), Envas (Cadila), Renitec (MSD)",
        "jan_aushadhi_price_inr": 1.00,
        "market_mrp_inr": 5.50,
        "text": (
            "Enalapril 5mg is an ACE inhibitor used in India for hypertension, chronic heart "
            "failure, and diabetic nephropathy. Inhibits angiotensin-converting enzyme (ACE), "
            "reducing Angiotensin II and aldosterone. Available as Enam (Emcure). Jan Aushadhi "
            "₹1.00 vs MRP ₹5.50. ACE inhibitors cause dry persistent cough in ~15–20% of South "
            "Asian patients (higher than Caucasians due to bradykinin accumulation) — switch to "
            "ARB (telmisartan, losartan) if intolerant. Contraindicated in bilateral renal artery "
            "stenosis and pregnancy. Monitor creatinine and potassium closely."
        ),
    },
    {
        "generic_name": "Sertraline Hydrochloride 50mg",
        "category": "Antidepressant — SSRI (Selective Serotonin Reuptake Inhibitor)",
        "indian_brands": "Serta (Sun Pharma), Zoloft (Pfizer), Daxid (Pfizer India)",
        "jan_aushadhi_price_inr": 4.00,
        "market_mrp_inr": 20.00,
        "text": (
            "Sertraline 50mg is the most commonly prescribed SSRI in India for depression, "
            "anxiety disorders, OCD, and PTSD. Inhibits serotonin (5-HT) reuptake transporter "
            "(SERT). Takes 2–4 weeks for full therapeutic effect — patients must be counselled. "
            "India's mental health burden is significant with 197 million Indians affected, "
            "yet treatment gap exceeds 80% due to stigma. Available as Serta (Sun Pharma), "
            "Daxid (Pfizer India). Jan Aushadhi ₹4.00 vs MRP ₹20.00. Side effects: nausea, "
            "sexual dysfunction, insomnia, sweating. Most tolerated SSRI. "
            "Monitor for suicidal ideation in first weeks, especially in young adults."
        ),
    },
]


# Indian-specific drug queries for OpenFDA enrichment
OPENFDA_QUERIES = [
    "metformin", "atorvastatin", "amlodipine", "telmisartan", "omeprazole",
    "azithromycin", "ciprofloxacin", "amoxicillin", "paracetamol", "levothyroxine",
    "clopidogrel", "rosuvastatin", "glimepiride", "pantoprazole", "montelukast",
    "cetirizine", "ferrous+sulfate", "folic+acid", "metronidazole",
    "hydroxychloroquine", "enalapril", "sertraline",
]


def _format_jan_aushadhi_text(entry: dict) -> str:
    return (
        f"Drug: {entry['generic_name']}\n"
        f"Category: {entry['category']}\n"
        f"Indian Brands: {entry['indian_brands']}\n"
        f"Jan Aushadhi Price: ₹{entry['jan_aushadhi_price_inr']} per unit\n"
        f"Market MRP: ₹{entry['market_mrp_inr']} per unit\n"
        f"Clinical Information: {entry['text']}\n"
        f"Cost Saving Tip: Available at all Pradhan Mantri Bhartiya Janaushadhi Pariyojana "
        f"(PMBJP) stores at ₹{entry['jan_aushadhi_price_inr']} vs MRP ₹{entry['market_mrp_inr']}. "
        f"Locate nearest store via the Jan Aushadhi Sugam mobile app or 1800-180-8080."
    )


def _fetch_openfda(drug_name: str) -> list[dict]:
    """Fetch 2 drug label records from OpenFDA for the given drug name."""
    records = []
    try:
        resp = requests.get(
            OPENFDA_BASE,
            params={"search": f"generic_name:{drug_name}", "limit": 2},
            timeout=15,
        )
        if resp.status_code != 200:
            return records

        for result in resp.json().get("results", []):
            parts = []
            for field in [
                "description", "indications_and_usage", "mechanism_of_action",
                "warnings", "adverse_reactions", "drug_interactions",
                "dosage_and_administration",
            ]:
                val = result.get(field)
                if val and isinstance(val, list) and val[0].strip():
                    # Truncate long fields to keep text size reasonable
                    parts.append(
                        f"{field.replace('_', ' ').title()}: {val[0][:600].strip()}"
                    )
            if parts:
                records.append({
                    "text": f"Drug Reference: {drug_name.title()}\n\n" + "\n\n".join(parts),
                    "source": "openfda",
                    "drug": drug_name,
                })
    except Exception as e:
        print(f"    OpenFDA error for {drug_name}: {e}")
    return records


def collect(output_path: Path) -> int:
    """
    Collect all drug data and write to output_path JSONL.

    Writes Jan Aushadhi entries first (high quality, instant), then
    enriches with OpenFDA data (requires network, rate-limited).

    Returns:
        Total number of records written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0

    # 1. Jan Aushadhi / PMBJP formulary entries
    print("  Writing Jan Aushadhi formulary entries...")
    records = [
        {
            "text": _format_jan_aushadhi_text(entry),
            "source": "jan_aushadhi",
            "drug": entry["generic_name"],
        }
        for entry in JAN_AUSHADHI_ENTRIES
    ]
    append_jsonl(output_path, records)
    total += len(records)
    print(f"  Jan Aushadhi: {len(records)} entries written")

    # 2. OpenFDA drug labels
    print("  Fetching OpenFDA drug labels...")
    openfda_count = 0
    for drug_name in OPENFDA_QUERIES:
        recs = _fetch_openfda(drug_name)
        if recs:
            append_jsonl(output_path, recs)
            openfda_count += len(recs)
            total += len(recs)
        time.sleep(0.30)  # OpenFDA limit: 240 req/min without key

    print(f"  OpenFDA: {openfda_count} label records written")
    return total

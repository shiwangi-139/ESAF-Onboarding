"""Every question on the onboarding form and the RM's field-visit form, shared by the form,
the dashboard and the document generator."""
from dataclasses import dataclass


def opts(*labels):
    return tuple((label, label) for label in labels)


@dataclass(frozen=True)
class Field:
    key: str
    hi: str
    en: str
    kind: str = "select"
    options: tuple = ()
    required: bool = True
    attrs: str = ""
    hint: str = ""


DOC_FIELDS = [
    ("aadhaar_front", "आधार कार्ड - आगे", "Aadhaar card – front"),
    ("aadhaar_back", "आधार कार्ड - पीछे", "Aadhaar card – back"),
    ("pan", "पैन कार्ड", "PAN card"),
    ("bank_proof", "बैंक पासबुक / कैंसिल चेक / स्टेटमेंट", "Bank passbook / cancelled cheque / statement"),
    ("education_cert", "शिक्षा प्रमाण पत्र (कम से कम 10वीं)", "Education certificate (min. 10th pass)"),
    ("photo", "हाल की पासपोर्ट साइज़ फोटो", "Recent passport-size photo"),
    ("payment_receipt", "₹1,999 रजिस्ट्रेशन भुगतान रसीद (+ डिवाइस शुल्क, यदि लागू)",
     "₹1,999 registration receipt (+ device cost, if applicable)"),
    ("shop_photo", "दुकान पर खड़े होकर अपनी फोटो", "Your photo at the shop (geo-stamp)"),
]
DOC_KEYS = [key for key, _, _ in DOC_FIELDS]

YES_NO = (("yes", "हाँ / Yes"), ("no", "नहीं / No"))

INDIAN_STATES = opts(
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep",
    "Puducherry",
)

YEARS = opts("1 साल से कम (<1 year)", "1-3 साल (1-3 years)", "3-5 साल (3-5 years)", "5+ साल (5+ years)")

STEPS = [
    {
        "n": 1, "hi": "मोबाइल", "en": "Mobile", "title": "मोबाइल नंबर / Mobile Number",
        "fields": [
            Field("mobile", "मोबाइल नंबर", "Mobile number", "tel",
                  attrs='pattern="[6-9][0-9]{9}" maxlength="10" inputmode="numeric" placeholder="10 अंकों का नंबर"',
                  hint="वही नंबर डालें जिस पर RM ने आपसे बात की / Use the number your RM called you on"),
            Field("email", "ईमेल (यदि है)", "Email (if any)", "email", required=False),
        ],
    },
    {"n": 2, "hi": "दस्तावेज़", "en": "Documents", "title": "दस्तावेज़ अपलोड करें / Upload Documents", "fields": []},
    {
        "n": 3, "hi": "व्यक्तिगत", "en": "Personal", "title": "व्यक्तिगत विवरण / Personal Details",
        "fields": [
            Field("full_name", "पूरा नाम", "Full name", "text",
                  hint="आधार/पैन पर जैसा लिखा है, वैसा ही / Exactly as on your Aadhaar/PAN"),
            Field("father_spouse_name", "पिता / पति का नाम", "Father's or spouse's name", "text"),
            Field("dob", "जन्म तिथि", "Date of birth", "date"),
            Field("gender", "लिंग", "Gender", options=opts("पुरुष (Male)", "महिला (Female)", "अन्य (Other)")),
            Field("marital_status", "वैवाहिक स्थिति", "Marital status",
                  options=opts("अविवाहित (Single)", "विवाहित (Married)", "विधवा/विधुर (Widow/Widower)")),
            Field("highest_education", "सबसे ऊँची पढ़ाई", "Highest education",
                  options=opts("10वीं (10th)", "12वीं (12th)", "स्नातक (Graduate)", "स्नातकोत्तर (Post-graduate)")),
            Field("pan_number", "पैन नंबर", "PAN number", "text",
                  attrs='pattern="[A-Za-z]{5}[0-9]{4}[A-Za-z]" maxlength="10" placeholder="ABCDE1234F" style="text-transform:uppercase"'),
            Field("aadhaar_last4", "आधार के आखिरी 4 अंक", "Last 4 digits of Aadhaar", "text",
                  attrs='pattern="[0-9]{4}" maxlength="4" inputmode="numeric"',
                  hint="पूरा आधार नंबर न डालें / Don't enter the full Aadhaar number"),
            Field("family_size", "परिवार में कुल सदस्य", "Total family members",
                  options=opts("1-2 सदस्य (1-2 members)", "3-4 सदस्य (3-4 members)", "5+ सदस्य (5+ members)")),
            Field("children_count", "बच्चों की संख्या", "Number of children",
                  options=opts("कोई नहीं (None)", "1", "2", "3", "4+")),
            Field("children_school", "क्या बच्चे पास के स्कूल में पढ़ते हैं?", "Children study in a nearby school?",
                  options=opts("लागू नहीं / Not applicable", "हाँ / Yes", "नहीं / No")),
        ],
    },
    {
        "n": 4, "hi": "पता व दुकान", "en": "Address & Shop", "title": "पता व दुकान / Address & Shop",
        "fields": [
            Field("address_line", "आधार पर लिखा पता (मकान नं., गली, गाँव/मोहल्ला)",
                  "Address as on Aadhaar (house no., street, village/locality)", "text"),
            Field("city", "शहर / कस्बा / तहसील", "City / town / tehsil", "text"),
            Field("state", "राज्य", "State", options=INDIAN_STATES),
            Field("pincode", "पिन कोड", "PIN code", "text",
                  attrs='pattern="[1-9][0-9]{5}" maxlength="6" inputmode="numeric"'),
            Field("lives_at_aadhaar_address", "क्या आप अभी आधार वाले पते पर ही रहते हैं?",
                  "Do you currently live at your Aadhaar address?", options=YES_NO),
            Field("local_address", "अभी का पूरा पता", "Current residential address", "text", required=False),
            Field("resident_type", "निवास प्रकार", "Resident type", options=opts("स्वयं का (Owned)", "किराए का (Rented)")),
            Field("years_at_location", "इस स्थान पर कब से रह रहे हैं", "Years at current location", options=YEARS),
            Field("shop_type", "दुकान की स्थिति", "Shop status", options=opts(
                "अपनी दुकान है (Have own shop)", "CSC से काम करूँगा (Will operate from a CSC, no formal shop)")),
            Field("shop_name", "दुकान का नाम (यदि है)", "Shop name (if any)", "text", required=False),
            Field("shop_address", "दुकान / व्यवसाय का पूरा पता, लैंडमार्क सहित", "Shop/business address, with landmark", "text"),
            Field("has_shop_proof", "क्या दुकान के पते का कोई प्रमाण है? (बिजली बिल / दुकान लाइसेंस)",
                  "Do you have shop address proof? (electricity bill / shop licence)", options=YES_NO,
                  hint="नहीं है तो भी ठीक है, हम घोषणा पत्र बना देंगे / If not, that's fine: we'll prepare a declaration"),
        ],
    },
    {
        "n": 5, "hi": "काम व बैंक", "en": "Work & Bank", "title": "काम, आय व बैंक / Work, Income & Bank",
        "fields": [
            Field("occupation", "व्यवसाय", "Occupation", options=opts(
                "दुकान / किराना (Shop / Kirana owner)", "कृषि (Agriculture)", "दिहाड़ी मजदूरी (Daily wage labour)",
                "स्वरोजगार / सेवा (Self-employed / Services)", "सरकारी नौकरी (Government job)", "अन्य (Other)")),
            Field("experience", "कुल कार्य अनुभव (नौकरी/व्यवसाय)", "Total work experience", options=YEARS),
            Field("income_band", "मुख्य स्रोत से औसत मासिक आय", "Monthly income – main source", options=opts(
                "10,000 से कम (Below 10,000)", "10,000 - 20,000", "20,000 - 30,000", "30,000 - 50,000",
                "50,000 से अधिक (Above 50,000)")),
            Field("secondary_income", "दूसरे स्रोत से औसत मासिक आय", "Monthly income – second source", options=opts(
                "कोई नहीं (None)", "5,000 से कम (Below 5,000)", "5,000 - 10,000", "10,000 - 20,000",
                "20,000 से अधिक (Above 20,000)")),
            Field("current_work_hours", "अभी के काम में रोज़ कितने घंटे देते हैं", "Hours/day on current work",
                  options=opts("4 घंटे से कम (<4 hrs)", "4-6 घंटे (4-6 hrs)", "6-8 घंटे (6-8 hrs)", "8+ घंटे (8+ hrs)")),
            Field("hours_available", "एजेंट के रूप में रोज़ कितने घंटे दे सकते हैं", "Hours/day available as agent",
                  options=opts("2 घंटे से कम (<2 hrs)", "2-4 घंटे (2-4 hrs)", "4-6 घंटे (4-6 hrs)", "6+ घंटे (6+ hrs)")),
            Field("initial_capital", "एजेंट बनने के लिए कितनी पूंजी लगा सकते हैं", "Capital to invest", options=opts(
                "5,000 से कम (Below 5,000)", "5,000-10,000", "10,000-25,000", "25,000 से अधिक (Above 25,000)")),
            Field("bank_account_number", "बैंक खाता नंबर (आपके अपने नाम पर)", "Bank account number (in your own name)", "text",
                  attrs='pattern="[0-9]{9,18}" maxlength="18" inputmode="numeric"'),
            Field("account_type", "खाते का प्रकार", "Account type", options=opts("बचत (Savings)", "चालू (Current)")),
            Field("bank_name", "बैंक का नाम", "Bank name", "text"),
            Field("bank_branch", "शाखा (ब्रांच) व शहर", "Branch and city", "text"),
            Field("ifsc", "बैंक IFSC कोड", "Bank IFSC code", "text",
                  attrs='pattern="[A-Za-z]{4}0[A-Za-z0-9]{6}" maxlength="11" placeholder="SBIN0001234" style="text-transform:uppercase"',
                  hint="पासबुक या चेक पर लिखा होता है / Printed on your passbook or cheque"),
            Field("micr", "MICR कोड (चेक पर 9 अंक, यदि है)", "MICR code (9 digits on cheque, if any)", "text", required=False,
                  attrs='pattern="[0-9]{9}" maxlength="9" inputmode="numeric"'),
        ],
    },
    {"n": 6, "hi": "समीक्षा", "en": "Review", "title": "समीक्षा करें / Review & Submit", "fields": []},
]

TOTAL_STEPS = len(STEPS)
FIELDS = {f.key: f for step in STEPS for f in step["fields"]}
STEP_FIELD_KEYS = {step["n"]: [f.key for f in step["fields"]] for step in STEPS}
STEP_FIELD_KEYS[2] = ["shop_lat", "shop_lng"]
REQUIRED_KEYS = [key for key, f in FIELDS.items() if f.required]
UPPERCASE_KEYS = {"ifsc", "pan_number"}

# Section D of the checklist: filled by the RM / visiting officer during the shop visit (Aceware FVR format).
FVR_FIELDS = [
    Field("state", "", "State", "text"),
    Field("cluster", "", "Cluster name", "text", required=False),
    Field("division", "", "Division", "text", required=False),
    Field("branch_name_code", "", "ESAF branch name with code", "text", required=False),
    Field("business_location_type", "", "Business location type", options=opts("BO", "CSC")),
    Field("officer_name", "", "Visiting officer name", "text"),
    Field("officer_emp_code", "", "Visiting officer employee code", "text"),
    Field("visit_date", "", "Date of visit", "date"),
    Field("spouse_father_occupation", "", "Spouse / father occupation", "text"),
    Field("establishment_type", "", "Type of establishment", options=opts("Shop", "Other")),
    Field("footfall", "", "Average footfall per day (number)", "number"),
    Field("road_access", "", "Accessibility to road / distance from road", "text"),
    Field("nearest_esaf", "", "Nearest ESAF BO/CSC name and distance (km)", "text"),
    Field("population", "", "Average population in the locality", "text"),
    Field("visibility", "", "Visibility and nearby places where people gather", "text"),
    Field("fi_nearby", "", "No. of other financial institutions nearby", "number"),
    Field("agents_within_5km", "", "No. of other agency banking agents within 5 km", "number"),
    Field("criminal_involvement", "", "Involvement in criminal activity", options=opts("No", "Yes")),
    Field("negative_credit_info", "", "Negative info from credit bureau / other sources (brief)", "text", required=False),
    Field("sangam_name_relation", "", "Sangam (SHG) name and relationship with member", "text", required=False),
    Field("sangam_member_name", "", "Sangam member name (if prospect is not the member)", "text", required=False),
    Field("remarks", "", "Your remarks about applicant quality", "textarea"),
    Field("recommendation", "", "Recommendation", options=opts("Recommended", "Rejected")),
    Field("cibil_score", "", "CIBIL score (filled from head office)", "text", required=False),
]

# Declaration sections the RM can add by hand (address ones are detected from the form automatically).
DECLARATION_TYPES = [
    ("name", "Name mismatch between documents"),
    ("dob", "Date of birth mismatch"),
    ("father_name", "Father's name mismatch"),
    ("signature", "Signature changed"),
]

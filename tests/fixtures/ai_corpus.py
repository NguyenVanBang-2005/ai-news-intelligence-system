"""Synthetic multi-topic news corpus for end-to-end / AI acceptance runs.

Entries are plain dicts (title, link, description, pubDate). `render_rss` turns a list
into an RSS 2.0 document. Group names are for humans (observing cluster quality only);
tests must not assert exact BERTopic labels or topic counts.
"""

from xml.sax.saxutils import escape

BASE = "https://corpus.example/news/"


def _item(group: str, slug: str, title: str, body: str, date: str | None = "") -> dict:
    return {
        "group": group,
        "title": title,
        "link": f"{BASE}{slug}",
        "description": body,
        "pubDate": date,
    }


GEN = [
    _item("gen", "gen-1", "Open language model beats larger rivals on reasoning benchmarks",
          "Researchers released an open-weight large language model that improves chain-of-thought "
          "reasoning. The transformer was pretrained on curated text and tuned with reinforcement "
          "learning from human feedback, and it scores higher on math and logic benchmarks.",
          "Mon, 28 Sep 2026 08:00:00 +0000"),
    _item("gen", "gen-2", "Chatbot assistants gain long-context memory",
          "Chatbot assistants can now keep entire conversations in a very long context window. "
          "Product teams say the language model remembers user preferences across sessions and "
          "answers follow-up questions without repeating instructions.",
          "Mon, 28 Sep 2026 09:00:00 +0000"),
    _item("gen", "gen-3", "Developers adopt code generation assistants at scale",
          "Software teams use generative models to write functions, unit tests and documentation. "
          "Engineers report faster prototyping, while reviewers warn that generated code still "
          "needs careful inspection for bugs and licensing issues.",
          "Mon, 28 Sep 2026 10:00:00 +0000"),
    _item("gen", "gen-4", "Fine-tuning small language models for customer support chatbots",
          "Companies are fine-tuning compact language models on support tickets to build cheap "
          "chatbots. The tuned models answer product questions accurately and run on a single "
          "server without calling an external generative API.",
          "Tue, 29 Sep 2026 08:00:00 +0000"),
    _item("gen", "gen-5", "Prompt engineering techniques for generative text models",
          "Practitioners share prompt templates, few-shot examples and system instructions that "
          "make generative text models follow formatting rules. Careful prompts reduce "
          "hallucinations in summarization and question answering tasks.",
          "Tue, 29 Sep 2026 09:00:00 +0000"),
]

ROBOTICS = [
    _item("robotics", "rob-1", "Humanoid robots start shifts in a logistics warehouse",
          "A logistics operator deployed humanoid robots that lift boxes and move totes between "
          "conveyor belts. The autonomous machines balance on two legs, climb ramps and "
          "coordinate with human workers on the warehouse floor.",
          "Mon, 28 Sep 2026 11:00:00 +0000"),
    _item("robotics", "rob-2", "Surgical robot arm completes delicate suture task",
          "A robotic arm guided by cameras performed precise suturing on tissue samples. "
          "Engineers say the manipulator's force sensors let the robot stitch with steady "
          "pressure, and surgeons supervise every motion.",
          "Mon, 28 Sep 2026 12:00:00 +0000"),
    _item("robotics", "rob-3", "Autonomous delivery robots expand to more city sidewalks",
          "Small wheeled robots now carry groceries along sidewalks and cross streets at "
          "signals. The delivery robots map their route, avoid pedestrians and call a remote "
          "operator when an obstacle blocks the path.",
          "Tue, 29 Sep 2026 11:00:00 +0000"),
    _item("robotics", "rob-4", "Robot vacuum learns room layouts with better navigation",
          "A new home robot builds a map of each room and plans cleaning routes around "
          "furniture. Its navigation software recognizes cables and socks so the robot avoids "
          "tangling its brushes.",
          "Tue, 29 Sep 2026 12:00:00 +0000"),
    _item("robotics", "rob-5", "Quadruped robot inspects an offshore platform",
          "A four-legged robot walked through an offshore platform to read gauges and detect "
          "gas leaks. The inspection robot climbs stairs and returns to its charging dock "
          "without a human operator on site.",
          "Wed, 30 Sep 2026 08:00:00 +0000"),
]

POLICY = [
    _item("policy", "pol-1", "EU begins enforcing rules for high-risk AI systems",
          "European regulators started enforcing the AI Act for high-risk systems. Providers "
          "must document training data, run risk assessments and register their models, or "
          "face fines under the new regulation.",
          "Mon, 28 Sep 2026 13:00:00 +0000"),
    _item("policy", "pol-2", "Court weighs copyright claims over AI training data",
          "Authors and publishers argue that copying books to train models violates copyright "
          "law. The court will decide whether training counts as fair use and whether "
          "developers owe licensing payments to rights holders.",
          "Mon, 28 Sep 2026 14:00:00 +0000"),
    _item("policy", "pol-3", "Government opens an AI safety institute to test frontier models",
          "The government announced a safety institute that will evaluate frontier models "
          "before release. Officials say the tests cover misuse risks, and companies agreed to "
          "share evaluation results with the regulator.",
          "Tue, 29 Sep 2026 13:00:00 +0000"),
    _item("policy", "pol-4", "Privacy regulators fine company over facial recognition database",
          "A data protection authority imposed a large fine for scraping photos into a facial "
          "recognition database without consent. The regulator ordered the company to delete "
          "the data and stop selling the service.",
          "Tue, 29 Sep 2026 14:00:00 +0000"),
    _item("policy", "pol-5", "Senate hearing debates federal AI legislation",
          "Lawmakers questioned experts about a federal bill on algorithmic accountability. "
          "Witnesses disagreed over licensing requirements, liability rules and whether new "
          "legislation could keep pace with technology.",
          "Wed, 30 Sep 2026 13:00:00 +0000"),
]

BUSINESS = [
    _item("business", "biz-1", "AI startup raises Series B funding led by venture investors",
          "An AI startup closed a Series B round at a valuation of one billion dollars. The "
          "venture investors said revenue tripled this year as enterprise customers signed "
          "multi-year contracts.",
          "Mon, 28 Sep 2026 15:00:00 +0000"),
    _item("business", "biz-2", "Chipmaker agrees to acquire AI accelerator startup",
          "A large chipmaker announced the acquisition of an accelerator startup for cash and "
          "stock. Analysts expect the deal to close next year after antitrust review and to "
          "boost data center sales.",
          "Mon, 28 Sep 2026 16:00:00 +0000"),
    _item("business", "biz-3", "Cloud provider reports quarterly revenue growth from AI services",
          "The cloud provider reported that quarterly revenue grew twenty percent as customers "
          "bought AI compute. Executives raised full-year guidance and plan to spend more on "
          "new data centers.",
          "Tue, 29 Sep 2026 15:00:00 +0000"),
    _item("business", "biz-4", "Venture funding for AI companies hits a record quarter",
          "Investors poured record sums into AI companies this quarter, led by late-stage "
          "rounds. Founders say competition for talent pushes salaries up while some "
          "investors warn of inflated valuations.",
          "Tue, 29 Sep 2026 16:00:00 +0000"),
    _item("business", "biz-5", "Enterprise software vendor bundles AI features into subscriptions",
          "A software vendor will include AI writing and analytics features in its enterprise "
          "subscription plans. The company expects higher renewal rates and says pricing "
          "will rise by ten percent.",
          "Wed, 30 Sep 2026 15:00:00 +0000"),
]

VISION = [
    _item("vision", "vis-1", "Diffusion model produces photorealistic images from sketches",
          "A diffusion model turns rough sketches into photorealistic images. Designers guide "
          "the image generator with text prompts and edit lighting, color and composition "
          "before exporting the picture.",
          "Mon, 28 Sep 2026 17:00:00 +0000"),
    _item("vision", "vis-2", "Object detection improves pedestrian safety for self-driving cars",
          "New object detection software spots pedestrians and cyclists at night with fewer "
          "misses. The computer vision system fuses camera frames and runs in real time on "
          "the vehicle's onboard processor.",
          "Mon, 28 Sep 2026 18:00:00 +0000"),
    _item("vision", "vis-3", "Medical imaging model flags early signs of lung disease",
          "A vision model analyzes chest scans and highlights suspicious nodules for "
          "radiologists. In a study of ten thousand images the system found early lesions "
          "that human readers had missed.",
          "Tue, 29 Sep 2026 17:00:00 +0000"),
    _item("vision", "vis-4", "Video generation model creates short film clips from text",
          "A video generation model produces ten-second clips from a text description. The "
          "frames stay consistent across motion, though the model still struggles with hands "
          "and fine text on screen.",
          "Tue, 29 Sep 2026 18:00:00 +0000"),
    _item("vision", "vis-5", "Satellite imagery model tracks deforestation by analyzing pixels",
          "Researchers trained a vision model on satellite images to detect illegal "
          "deforestation. The system labels forest loss within days and sends alerts to "
          "rangers with map coordinates.",
          "Wed, 30 Sep 2026 17:00:00 +0000"),
]

HEALTH = [
    _item("health", "hlt-1", "AI predicts protein structures to speed up drug discovery",
          "A protein folding model predicts three-dimensional structures of molecules in "
          "minutes. Pharmaceutical chemists use the predictions to screen drug candidates "
          "before running costly lab experiments.",
          "Mon, 28 Sep 2026 19:00:00 +0000"),
    _item("health", "hlt-2", "Clinical trial uses machine learning to select patients",
          "A clinical trial applies machine learning to match patients with experimental "
          "treatments. Investigators say the algorithm shortens enrollment and reduces "
          "dropout in the oncology study.",
          "Mon, 28 Sep 2026 20:00:00 +0000"),
    _item("health", "hlt-3", "Hospital deploys AI triage tool in the emergency department",
          "Doctors in an emergency department use an AI triage tool that ranks patients by "
          "risk of deterioration. Nurses receive alerts about sepsis and the hospital reports "
          "faster treatment times.",
          "Tue, 29 Sep 2026 19:00:00 +0000"),
    _item("health", "hlt-4", "Wearable sensors and AI detect irregular heart rhythm",
          "A smartwatch algorithm detects atrial fibrillation from pulse signals. Cardiologists "
          "confirmed most alerts with an electrocardiogram and urged patients to share the "
          "data during checkups.",
          "Tue, 29 Sep 2026 20:00:00 +0000"),
    _item("health", "hlt-5", "Genomics team applies AI to find rare disease variants",
          "Geneticists use a machine learning pipeline to rank DNA variants linked to rare "
          "diseases. The method cut diagnosis time for children from months to weeks in "
          "a pilot at three hospitals.",
          "Wed, 30 Sep 2026 19:00:00 +0000"),
]

VIETNAMESE = [
    _item("vi-llm", "vi-1", "Mô hình ngôn ngữ lớn mã nguồn mở cải thiện khả năng suy luận",
          "Các nhà nghiên cứu công bố một mô hình ngôn ngữ lớn mã nguồn mở có khả năng suy luận "
          "tốt hơn. Chatbot dùng mô hình này trả lời câu hỏi bằng tiếng Việt chính xác hơn.",
          "Mon, 28 Sep 2026 07:00:00 +0700"),
    _item("vi-llm", "vi-2", "Chatbot trí tuệ nhân tạo hỗ trợ khách hàng bằng tiếng Việt",
          "Nhiều doanh nghiệp triển khai chatbot dùng mô hình ngôn ngữ để trả lời khách hàng. "
          "Hệ thống hiểu câu hỏi tự nhiên và gợi ý câu trả lời cho nhân viên hỗ trợ.",
          "Tue, 29 Sep 2026 07:00:00 +0700"),
    _item("vi-llm", "vi-3", "Sinh viên huấn luyện mô hình ngôn ngữ nhỏ cho tiếng Việt",
          "Một nhóm sinh viên huấn luyện mô hình ngôn ngữ nhỏ trên dữ liệu tiếng Việt. "
          "Mô hình chạy được trên máy tính cá nhân và tạo văn bản mạch lạc.",
          "Wed, 30 Sep 2026 07:00:00 +0700"),
    _item("vi-policy", "vi-4", "Quốc hội thảo luận dự thảo luật về trí tuệ nhân tạo",
          "Các đại biểu Quốc hội thảo luận dự thảo luật quy định trách nhiệm của doanh nghiệp "
          "phát triển hệ thống trí tuệ nhân tạo. Dự thảo yêu cầu đánh giá rủi ro và bảo vệ dữ liệu "
          "cá nhân của người dùng.",
          "Mon, 28 Sep 2026 09:00:00 +0700"),
    _item("vi-policy", "vi-5", "Bộ ngành đề xuất quy định an toàn cho hệ thống AI rủi ro cao",
          "Cơ quan quản lý đề xuất quy định về an toàn đối với hệ thống AI rủi ro cao. "
          "Doanh nghiệp phải đăng ký, minh bạch dữ liệu huấn luyện và chịu xử phạt khi vi phạm.",
          "Tue, 29 Sep 2026 09:00:00 +0700"),
    _item("vi-policy", "vi-6", "Chuyên gia kêu gọi khung pháp lý về bản quyền dữ liệu huấn luyện",
          "Các chuyên gia pháp lý kêu gọi khung pháp lý rõ ràng về bản quyền khi dùng tác phẩm "
          "để huấn luyện mô hình AI. Họ đề xuất cơ chế cấp phép và trả phí cho chủ sở hữu.",
          "Wed, 30 Sep 2026 09:00:00 +0700"),
]

# Near/exact duplicates of articles above, published under different URLs.
DUPLICATES = [
    _item("dup-gen-1", "dup-gen-1",
          "Open language model beats larger rivals on reasoning benchmarks - wire copy",
          GEN[0]["description"] + " (Syndicated)", "Mon, 28 Sep 2026 08:30:00 +0000"),
    _item("dup-rob-1", "dup-rob-1", "Warehouse deploys humanoid robots to move boxes",
          "A logistics operator put humanoid robots to work lifting boxes and moving totes "
          "between conveyor belts. The autonomous machines walk on two legs, climb ramps and "
          "work alongside people on the warehouse floor.", "Mon, 28 Sep 2026 11:30:00 +0000"),
    _item("dup-pol-1", "dup-pol-1", POLICY[0]["title"], POLICY[0]["description"],
          "Mon, 28 Sep 2026 13:30:00 +0000"),
    _item("dup-vi-1", "dup-vi-1", VIETNAMESE[3]["title"], VIETNAMESE[3]["description"],
          "Mon, 28 Sep 2026 09:30:00 +0700"),
]

# Cannot be analysed: no body, or a body that merely repeats the headline.
NO_CONTENT = [
    _item("empty", "empty-1", "Headline only story about an AI conference", "", None),
    _item("empty", "empty-2", "Another headline with no body text", "", "not a real date"),
    _item("empty", "empty-3", "Body repeats the title", "Body repeats the title", None),
]

# One huge body: feed truncates at max_article_content_chars, AI at 10_000 characters.
LONG = [
    _item("long", "long-1", "Very long explainer on neural network training",
          ("Neural networks learn by gradient descent on large datasets, adjusting weights "
           "to reduce loss. ") * 400, "Wed, 30 Sep 2026 10:00:00 +0000"),
]

CLUSTERABLE = GEN + ROBOTICS + POLICY + BUSINESS + VISION + HEALTH
ALL_ITEMS = CLUSTERABLE + VIETNAMESE + DUPLICATES + NO_CONTENT + LONG


def render_rss(items: list[dict], title: str = "Corpus feed") -> bytes:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{escape(title)}</title><link>https://corpus.example/</link>"
        "<description>synthetic</description>",
    ]
    for item in items:
        parts.append("<item>")
        parts.append(f"<title>{escape(item['title'])}</title>")
        parts.append(f"<link>{escape(item['link'])}</link>")
        if item["description"]:
            parts.append(f"<description>{escape(item['description'])}</description>")
        if item["pubDate"]:
            parts.append(f"<pubDate>{escape(item['pubDate'])}</pubDate>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "\n".join(parts).encode("utf-8")

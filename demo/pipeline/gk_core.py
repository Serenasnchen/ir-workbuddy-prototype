"""M4 数字守门员——确定性核心库（文本层、单位归一、指标别名、句子级抽取）。

不调用任何大模型，不发起网络请求。被 gatekeeper.py / inject.py / test_gatekeeper.py 共用。

文本层说明：
  data/src/ir_official/*.txt 由 pdftotext -layout 以 Latin-1 编码生成——中文全部丢失，
  英文表格列被打散。因此本模块用 PyMuPDF（pymupdf）对同一批 PDF 重新抽取 UTF-8 文本，
  落盘到 demo/data/raw/m4/txt/<季度>_<文件>.txt（每页以 "=== page N ===" 开头），
  所有"行号"均指该派生文件的行号；另给出原 pdftotext .txt 中含同一数字的行号（txt_line）供交叉核对。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_SRC, ROOT  # noqa: E402

IR = DATA_SRC / "ir_official"
RAW = ROOT / "demo" / "data" / "raw" / "m4"
TXT = RAW / "txt"

QUARTERS = ["1Q25", "2Q25", "3Q25", "4Q25", "1Q26", "2Q26"]
TARGET = "2Q26"
KINDS = ["release_en", "release_zh", "hkex_en", "hkex_zh", "ppt"]
REF_KINDS = ["hkex_en", "hkex_zh", "ppt"]          # 草稿检查的"已披露"基准（不含新闻稿本身）
LANG = {"release_en": "en", "release_zh": "zh", "hkex_en": "en", "hkex_zh": "zh", "ppt": "en"}
KIND_ZH = {"release_en": "英文业绩新闻稿", "release_zh": "中文业绩新闻稿", "hkex_en": "港交所英文业绩公告",
           "hkex_zh": "港交所中文业绩公告", "ppt": "业绩演示 PPT"}
PREV_Y = {"1Q26": "1Q25", "2Q26": "2Q25"}
PREV_Q = {"2Q25": "1Q25", "3Q25": "2Q25", "4Q25": "3Q25", "1Q26": "4Q25", "2Q26": "1Q26"}

# ---------------------------------------------------------------------------
# 1. 字符归一（全部为 1:1 替换，保证字符位置与原文一致）
# ---------------------------------------------------------------------------
_PUNCT = {"（": "(", "）": ")", "，": ",", "；": ";", "：": ":", "％": "%", "／": "/", "╱": "/", "－": "-",
          "–": "-", "—": "-", "−": "-", "\u3000": " ", "\xa0": " ", "’": "'", "‘": "'", "“": '"', "”": '"',
          "\u2009": " ", "\u202f": " ", "＋": "+", "～": "~", "\u2002": " ", "\u2003": " ",
          # Wingdings/Symbol 私用区项目符号 → 标准符号
          "\uf0a7": "▪", "\uf06e": "▪", "\uf0d8": "▪", "\uf09f": "•", "\uf0b7": "•", "\uf0fc": "•"}
# 繁→简（仅覆盖港交所中文公告中出现的常用字；逐字替换，长度不变）
_T2S_PAIRS = (
    "幣币資资務务計计億亿營营個个於于經经權权額额動动萬万產产國国業业審审價价為为長长應应稅税淨净銷销佔占"
    "報报內内損损準准際际變变團团聯联會会購购現现據据攤摊虧亏處处無无數数發发劃划們们項项註注銀银與与獎奖"
    "勵励遊游總总撥拨員员賬账該该關关屬属並并戲戏調调對对轉转場场間间備备環环視视減减債债後后負负佈布擔担"
    "僱雇響响廣广來来過过將将舊旧條条閱阅時时續续載载東东體体礎础騰腾獲获適适綜综優优採采製制義义規规躍跃"
    "訊讯進进區区認认須须歐欧結结確确號号費费編编買买運运圓圆實实層层詞词庫库節节陳陈師师驅驱電电獻献潤润"
    "簡简儲储島岛樂乐責责績绩證证領领選选級级貢贡雲云餘余彙汇貨货歸归冊册納纳週周獨独穩稳併并較较決决舉举"
    "遞递課课釐厘執执釋释顯显頻频測测創创腦脑匯汇錄录贖赎類类譽誉沖冲組组細细蘭兰賴赖構构辦办強强帶带貸贷"
    "換换從从識识補补賃赁慣惯術术許许議议沒没繼继風风險险輪轮當当張张慮虑離离謝谢堅坚聲声櫃柜觀观豐丰統统"
    "陣阵討讨論论網网絡络薦荐質质擴扩兌兑評评狀状況况滿满繳缴連连徵征潛潜齡龄賒赊詳详濟济遠远屆届馬马楊杨"
    "織织華华終终顧顾賦赋邁迈頂顶裡里點点訪访問问願愿擇择啟启範范圍围試试專专隱隐輕轻勁劲劇剧鳴鸣幫帮態态"
    "閉闭寶宝榮荣機机軟软園园訴诉訟讼說说讀读歷历亞亚賺赚則则開开稱称線线蓋盖紅红錢钱鐵铁衛卫儀仪傳传勢势"
    "協协單单參参學学寫写導导廠厂廢废戰战擊击擁拥擬拟斷断書书極极標标樣样種种積积筆笔簽签紀纪純纯給给絕绝"
    "維维緊紧練练聽听興兴藝艺裝装覺觉親亲託托記记話话語语請请護护貿贸賣卖賽赛車车農农這这還还邊边醫医門门"
    "陽阳階阶隨随雙双難难題题驗验髮发麼么鏈链錯错頁页飛飞養养齊齐黨党攜携億亿約约設设訂订預预麗丽臺台灣湾"
    "億亿匱匮衝冲輸输鎖锁縮缩鬆松嚴严壓压獎奖奪夺僅仅倉仓傷伤償偿儘尽兩两剛刚劑剂勞劳勝胜卻却厲厉嗎吗圖图"
    "壞坏壽寿夠够夢梦奮奋婦妇寧宁尋寻嶺岭幹干廳厅徑径徹彻恆恒惡恶愛爱慶庆憂忧懷怀懼惧掃扫掛挂揚扬搖摇撐撑"
    "擋挡擠挤攝摄敵敌敘叙晉晋暢畅暫暂曆历極极歡欢歲岁殘残殺杀氣气漢汉漲涨潔洁濕湿澤泽灑洒煉炼煙烟熱热燈灯"
    "爭争爾尔牆墙獄狱瑪玛畫画畢毕療疗盡尽監监盤盘禮礼稅税穀谷窮穷築筑籌筹糧粮紙纸綠绿緒绪罰罚職职腳脚莊庄"
    "葉叶藥药蘇苏蟲虫複复覽览詐诈詢询誠诚誤误諾诺謀谋講讲謹谨譯译豬猪貞贞販贩貪贪貴贵貼贴賀贺賓宾賞赏賠赔"
    "賢贤賤贱趨趋跡迹踐践軌轨軍军輔辅輛辆辭辞違违郵邮針针銳锐錶表鍾钟鎮镇鏡镜鐘钟閃闪閒闲闊阔隻只雖虽雜杂"
    "靜静順顺頒颁頓顿顆颗飯饭飲饮館馆鬥斗偽伪兒儿湊凑廂厢彈弹復复憑凭敗败暈晕樓楼溝沟滅灭牽牵異异盜盗碼码"
    "礙碍紛纷紡纺絲丝綁绑綱纲緣缘縣县繞绕繪绘纜缆羅罗聖圣聞闻膚肤膠胶臨临艦舰蓮莲藍蓝蘋苹虛虚眾众衆众裏里"
    "誇夸誘诱誕诞諸诸謂谓譜谱豎竖貶贬賭赌贏赢軸轴輝辉輯辑轄辖辯辩迴回鄰邻醜丑鈣钙鉅巨鋼钢錦锦鍊炼鍋锅鑑鉴"
    "閣阁隸隶雞鸡霧雾韓韩頭头顏颜飄飘餅饼饋馈駐驻驚惊鬱郁魯鲁鮮鲜鴻鸿鹽盐麥麦黃黄齒齿龍龙盧卢鑽钻幾几竊窃"
    "鍵键陸陆隊队靈灵慮虑僑侨嘗尝噸吨團团壇坛奧奥孫孙寢寝專专屍尸峽峡帥帅帳帐廟庙懇恳戀恋拋抛捨舍損损搶抢"
    "擺摆攔拦攪搅斃毙樞枢橋桥檔档檢检欄栏毆殴氫氢汙污涇泾淚泪淪沦渾浑湯汤滬沪滲渗滯滞漁渔潑泼潰溃澆浇濃浓"
    "濱滨瀏浏灘滩燦灿爐炉獅狮獸兽瓏珑疊叠瘡疮癢痒皚皑睜睁瞞瞒矯矫碩硕磚砖禱祷禿秃稈秆種种窩窝竇窦箋笺箏筝"
    "範范篩筛籃篮籠笼糞粪紋纹紐纽紗纱紳绅紹绍絆绊絞绞絨绒綏绥綫线綬绶綸纶綺绮綻绽綽绰緋绯緞缎緬缅緯纬締缔"
    "縫缝縱纵縷缕繁繁繡绣繩绳纏缠纖纤罵骂羈羁習习聰聪肅肃脅胁脈脉脫脱脹胀腎肾腫肿腸肠臘腊臟脏艙舱艷艳茲兹"
    "荊荆萊莱葦苇蒼苍蔣蒋蔥葱蔭荫蕩荡蕪芜蕭萧薈荟薑姜薦荐藹蔼蘆芦蘊蕴蘿萝蝦虾螞蚂蠟蜡襪袜襯衬觸触訃讣訊讯"
    "訓训託托詛诅詠咏誦诵諷讽謊谎謠谣譏讥讓让讚赞豈岂貓猫賄贿賊贼賬账賺赚贊赞趕赶趙赵躉趸軀躯軋轧軒轩"
    "載载輩辈輻辐轎轿轟轰辦办遜逊遷迁遺遗鄉乡釀酿鈔钞鈴铃鉛铅銅铜銘铭鋒锋鋪铺錘锤鍛锻鎊镑鑄铸鑰钥閘闸閩闽"
    "闖闯闡阐陰阴陝陕隕陨韋韦頌颂頸颈頰颊顛颠颱台餓饿餵喂駕驾駛驶騎骑騙骗髒脏鬍胡鯨鲸鵬鹏鷹鹰麵面黴霉齋斋"
    "龜龟傭佣傑杰傘伞儉俭厭厌吳吴喚唤喪丧嘆叹嚇吓囑嘱塗涂塵尘墜坠壯壮夾夹嬰婴寵宠屜屉屢屡嶄崭廚厨憐怜憤愤"
    "憶忆懲惩懶懒捲卷揮挥撈捞撓挠撲扑擾扰擱搁擲掷攏拢攢攒棧栈楓枫槍枪樁桩檯台櫥橱欖榄殤殇殯殡氈毡洶汹濁浊"
    "濺溅瀉泻瀕濒瀝沥燙烫燭烛爍烁犢犊狽狈猙狰獰狞痙痉瘧疟癥症竅窍簍篓簫箫粧妆紂纣紉纫紓纾絀绌絢绚絳绛綑捆"
    "緘缄緩缓縛缚縝缜縞缟縵缦繃绷繕缮繚缭繭茧繹绎纓缨缽钵罌罂聳耸臍脐舖铺芻刍莢荚萬万蒔莳蓀荪蔞蒌蕎荞薊蓟"
    "薔蔷藎荩藪薮蘄蕲蘚藓蘭兰覓觅訛讹訝讶訣诀詭诡誹诽諧谐諮咨謁谒譁哗譴谴豔艳賂赂賑赈賜赐賠赔贓赃贖赎"
    "躊踌軼轶輟辍轍辙逕径遞递鄭郑醬酱釘钉鈍钝鉗钳銜衔鋁铝錨锚鍍镀鎔熔鎳镍鏟铲鐲镯鑼锣閥阀闔阖隴陇雛雏"
    "頃顷頗颇顎颚顫颤颳刮颶飓颼飕飼饲餃饺餒馁饅馒駁驳駝驼駱骆騷骚驕骄驢驴驟骤骯肮鬧闹鯊鲨鴉鸦鴨鸭鵝鹅"
    "鶴鹤鷗鸥麼么黨党鼴鼹齣出齦龈龐庞彥彦滙汇資资財财戶户別别棄弃達达娛娱遲迟彌弥倫伦韌韧寬宽摯挚競竞鑒鉴"
    "鞏巩見见桿杆繫系亂乱側侧夥伙躋跻"
)
T2S = {}
for _i in range(0, len(_T2S_PAIRS) - 1, 2):
    _t, _s = _T2S_PAIRS[_i], _T2S_PAIRS[_i + 1]
    if _t != _s:
        T2S[_t] = _s
_TRANS_EN = str.maketrans(_PUNCT)
_TRANS_ZH = str.maketrans({**_PUNCT, **T2S})


def normalize(s, lang):
    """1:1 字符替换：全角标点→半角、各类破折号→'-'；中文另做繁→简。长度不变。"""
    return s.translate(_TRANS_ZH if lang == "zh" else _TRANS_EN)


def is_cjk(ch):
    return "一" <= ch <= "鿿"


# ---------------------------------------------------------------------------
# 2. 文本层：PyMuPDF 抽取 → 派生 UTF-8 文本（带页标记）；原 pdftotext .txt 行号映射
# ---------------------------------------------------------------------------
def rel(p):
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def ensure_text(q, kind, src_pdf=None, out=None):
    pdf = Path(src_pdf) if src_pdf else IR / f"{q}_{kind}.pdf"
    out = Path(out) if out else TXT / f"{q}_{kind}.txt"
    if out.exists():
        return out
    import pymupdf  # 仅在派生文本缺失时需要
    doc = pymupdf.open(str(pdf))
    lines = []
    for i, page in enumerate(doc):
        lines.append(f"=== page {i + 1} ===")
        lines.extend(x.rstrip() for x in page.get_text().split("\n"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


_ORIG_CACHE = {}


def orig_pages(q, kind):
    """原 pdftotext .txt：返回 [(全局行号, 页码, 行文本)]（按 \\f 分页，Latin-1 读入）。"""
    key = (q, kind)
    if key not in _ORIG_CACHE:
        p = IR / f"{q}_{kind}.txt"
        rows = []
        if p.exists():
            page = 1
            for i, line in enumerate(p.read_bytes().decode("latin-1").split("\n")):
                page += line.count("\f")
                rows.append((i + 1, page, line.replace("\f", "").rstrip("\r")))
        _ORIG_CACHE[key] = rows
    return _ORIG_CACHE[key]


def orig_line(q, kind, page, token, hint=""):
    """在原 pdftotext .txt 同一页内找包含 token 的行；多处命中时取与 hint 词重合最多者。"""
    if not token:
        return None
    hints = set(w.lower() for w in re.findall(r"[A-Za-z]{4,}", hint))
    best = None
    pat = re.compile(r"(?<![\d.,])" + re.escape(token) + r"(?![\d])")
    for ln, pg, text in orig_pages(q, kind):
        if pg != page or not pat.search(text):
            continue
        score = len(hints & set(w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)))
        if best is None or score > best[0]:
            best = (score, ln)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# 3. 数字与单位归一
#    货币金额统一为"百万"（RMB/HKD/USD）；无量级的人民币金额（每股、汇率）为 RMB1；
#    数量统一为"百万"（count）；百分比 pct；百分点 ppt。half = 末位单位的一半（四舍五入容差）。
# ---------------------------------------------------------------------------
NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
SCALE = {"trillion": 1e6, "billion": 1e3, "bn": 1e3, "million": 1.0, "mn": 1.0, "m": 1.0,
         "万亿": 1e6, "千亿": 1e5, "百亿": 1e4, "亿": 100.0, "千万": 10.0, "百万": 1.0, "万": 0.01}
RE_MONEY_EN = re.compile(
    r"(?P<approx>~\s?|approximately\s|about\s|around\s|over\s|more than\s|nearly\s)?(?P<cur>RMB|HKD|HK\$|USD|US\$)\s?"
    r"(?P<num>" + NUM + r")(?:\s?(?P<scale>trillion|billion|million|bn|mn)(?![A-Za-z]))?", re.I)
RE_MONEY_ZH = re.compile(
    r"(?P<approx>约|超过|逾|近)?\s?(?P<cur1>人民币|港币|美元)?\s?(?P<num>" + NUM + r")\s?"
    r"(?P<scale>万亿|千亿|百亿|亿|千万|百万|万)?\s?(?P<cur2>元|港元|美元)")
RE_PCT = re.compile(r"(?<![A-Za-z0-9_.])(?P<sign>[+\-])?(?P<num>\d+(?:\.\d+)?)\s?%")
RE_PPT = re.compile(r"(?<![A-Za-z0-9_.])(?P<sign>[+\-])?(?P<num>\d+(?:\.\d+)?)\s?(?:ppts?\b|pp\b|percentage points?\b|个百分点)")
RE_COUNT_EN = re.compile(
    r"(?P<approx>~\s?|approximately\s|about\s|over\s|more than\s)?(?<![\w.])(?P<num>" + NUM + r")\s?"
    r"(?P<scale>billion|million|m)(?![A-Za-z])", re.I)
RE_COUNT_ZH = re.compile(r"(?P<approx>约|超过|逾)?(?<![\d.])(?P<num>" + NUM + r")\s?(?P<scale>亿|万)(?!\s?(?:元|港元|美元))")
MONEY_CLS = {"RMB", "HKD", "USD", "RMB1", "HKD1", "USD1"}


class Num:
    __slots__ = ("cls", "value", "half", "raw", "start", "end", "approx", "token", "dec")

    def __init__(self, cls, value, half, raw, start, end, approx=False, token="", dec=0):
        self.cls, self.value, self.half, self.raw = cls, value, half, raw
        self.start, self.end, self.approx, self.token, self.dec = start, end, approx, token, dec

    def __repr__(self):
        return f"Num({self.cls},{self.value:g}±{self.half:g},{self.raw!r})"

    def as_dict(self):
        return {"cls": self.cls, "value": round(self.value, 6), "half": round(self.half, 6), "raw": self.raw}


def _numval(s):
    s = s.replace(",", "")
    dec = len(s.split(".")[1]) if "." in s else 0
    return float(s), dec


def _cur_cls(cur):
    cur = cur.upper().replace("HK$", "HKD").replace("US$", "USD")
    return {"RMB": "RMB", "HKD": "HKD", "USD": "USD", "人民币": "RMB", "港币": "HKD", "美元": "USD",
            "元": "RMB", "港元": "HKD"}.get(cur, cur)


def parse_numbers(text, lang):
    """抽取带单位的数字（金额/数量/百分比/百分点）。裸数字（年份、页码、脚注号）一律不抽。"""
    out, used = [], []

    def free(a, b):
        return all(b <= s or a >= e for s, e in used)

    def add(n):
        out.append(n)
        used.append((n.start, n.end))

    if lang == "en":
        for m in RE_MONEY_EN.finditer(text):
            v, dec = _numval(m.group("num"))
            cur = _cur_cls(m.group("cur"))
            sc = (m.group("scale") or "").lower()
            if sc:
                f = SCALE[sc]
                add(Num(cur, v * f, 0.5 * 10 ** -dec * f, m.group(0).strip(), m.start(), m.end(),
                        bool(m.group("approx")), m.group("num"), dec))
            else:
                add(Num(cur + "1", v, 0.5 * 10 ** -dec, m.group(0).strip(), m.start(), m.end(),
                        bool(m.group("approx")), m.group("num"), dec))
    else:
        for m in RE_MONEY_ZH.finditer(text):
            v, dec = _numval(m.group("num"))
            cur2 = m.group("cur2")
            cur = _cur_cls(m.group("cur1") or "") if m.group("cur1") else _cur_cls(cur2)
            if cur2 == "港元":
                cur = "HKD"
            elif cur2 == "美元":
                cur = "USD"
            sc = m.group("scale")
            if not sc and not m.group("cur1") and re.fullmatch(r"\d", m.group("num")):
                continue  # 脚注序号 + "美元/元"（如"2 美元数据基于…"），不是金额
            st = m.start("num") if not m.group("cur1") and not m.group("approx") else m.start()
            if sc:
                f = SCALE[sc]
                add(Num(cur, v * f, 0.5 * 10 ** -dec * f, m.group(0).strip(), st, m.end(),
                        bool(m.group("approx")), m.group("num"), dec))
            else:
                add(Num(cur + "1", v, 0.5 * 10 ** -dec, m.group(0).strip(), st, m.end(),
                        bool(m.group("approx")), m.group("num"), dec))
    for m in RE_PPT.finditer(text):
        if free(m.start(), m.end()):
            v, dec = _numval(m.group("num"))
            if m.group("sign") == "-":
                v = -v
            add(Num("ppt", v, 0.5 * 10 ** -dec, m.group(0).strip(), m.start(), m.end(), False, m.group("num"), dec))
    for m in RE_PCT.finditer(text):
        if free(m.start(), m.end()):
            v, dec = _numval(m.group("num"))
            if m.group("sign") == "-":
                v = -v
            add(Num("pct", v, 0.5 * 10 ** -dec, m.group(0).strip(), m.start(), m.end(), False, m.group("num"), dec))
    rc = RE_COUNT_EN if lang == "en" else RE_COUNT_ZH
    for m in rc.finditer(text):
        if free(m.start(), m.end()):
            v, dec = _numval(m.group("num"))
            sc = m.group("scale").lower() if lang == "en" else m.group("scale")
            f = SCALE[sc]
            add(Num("count", v * f, 0.5 * 10 ** -dec * f, m.group(0).strip(), m.start(), m.end(),
                    bool(m.group("approx")), m.group("num"), dec))
    out.sort(key=lambda n: n.start)
    return out


def consistent(a_val, a_half, b_val, b_half):
    """两个四舍五入区间是否有正长度交集（端点相切视为不一致）。"""
    lo = max(a_val - a_half, b_val - b_half)
    hi = min(a_val + a_half, b_val + b_half)
    eps = 1e-9 * max(1.0, abs(a_val), abs(b_val))
    if a_half == 0 or b_half == 0:
        return hi >= lo - eps
    return hi - lo > eps


def judge_mismatch(a_val, a_half, b_val, b_half):
    """不一致时的分类：数量级/单位差异、末位差异（超出四舍五入但不超过一个显示单位）、实质差异。"""
    if a_val and b_val:
        for k in (10, 100, 1000, 10000, 0.1, 0.01, 0.001, 0.0001):
            if consistent(a_val * k, a_half * k, b_val, b_half):
                return "数量级/单位差异"
    diff = abs(a_val - b_val)
    if diff <= a_half + b_half + 2 * max(a_half, b_half) + 1e-9:
        return "末位差异"
    return "实质差异"


def fmt_val(cls, v):
    if cls in ("RMB", "HKD", "USD"):
        return f"{cls} {v:,.0f} 百万" if abs(v - round(v)) < 1e-6 else f"{cls} {v:,.1f} 百万"
    if cls == "count":
        return f"{v:,.2f} 百万".replace(".00 ", " ")
    if cls in ("pct", "ppt"):
        return f"{v:g}%" if cls == "pct" else f"{v:g}ppt"
    return f"{v:g}"


# ---------------------------------------------------------------------------
# 4. 文档与段落
# ---------------------------------------------------------------------------
BULLETS = {"▪", "•", "-", "", "h", "‧", "o", "§", "", "■", "●", "*"}
TOP_BULLETS = {"▪", "", "•", "h", "‧", "■", "●"}
RE_CELL = re.compile(r"^[\(\-+~]?\d[\d,]*(?:\.\d+)?\)?\s?(?:%|ppt|x)?$|^(?:stable|NA|NM|N/A|-|稳定|持平|不适用)$", re.I)
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4}
# 新闻稿正文之后的固定章节（遇到即单独成段，期间记为 OTHER）
RE_SECTION_STOP = re.compile(r"^(About Tencent|关于腾讯|Non-IFRS Financial Measures|非国际财务报告准则财务计量|"
                             r"Forward-Looking Statements|前瞻性陈述)\s*$")
# 口径不同的特殊表述（如"剔除分占联营公司盈利后"），不做数值核对
RE_SKIP_SCOPE = re.compile(r"excluding[^.;]{0,80}(?:associates|joint ventures)|剔除[^。;]{0,40}(?:联营|合营)", re.I)


def _cn_year(s):
    d = {"零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    return "".join(d.get(c, c) for c in s)


def heading_period(t, lang):
    """识别章节标题并返回其期间：'1Q26' 形式的季度，'FY'（全年），'OTHER'（六个月/九个月等）。"""
    if lang == "en":
        m = re.match(r"^([1-4])Q(20\d\d)\s+(Financial Highlights|Management Discussion|Business Review|Operating)", t)
        if m:
            return f"{m.group(1)}Q{m.group(2)[2:]}"
        if re.match(r"^FY20\d\d\b", t) or re.match(r"^20\d\d (Full Year|Annual)\b", t):
            return "FY"
        m = re.match(r"^(First|Second|Third|Fourth) Quarter of (20\d\d) Compared to", t, re.I)
        if m:
            qn = {"first": 1, "second": 2, "third": 3, "fourth": 4}[m.group(1).lower()]
            return f"{qn}Q{m.group(2)[2:]}"
        if re.match(r"^(Year Ended 31 December 20\d\d Compared|Six Months Ended .* Compared|First Half of 20\d\d Compared|"
                    r"Nine Months Ended .* Compared)", t, re.I):
            return "OTHER"
        return None
    m = re.match(r"^([1-4])Q(20\d\d)\s?(财务摘要|管理层讨论|业务回顾|经营数据)", t)
    if m:
        return f"{m.group(1)}Q{m.group(2)[2:]}"
    if re.match(r"^20\d\d\s?年\s?(财务摘要|管理层讨论|业务回顾|可持续)", t):
        return "FY"
    m = re.match(r"^二零(二.)年第(一|二|三|四)季(业绩摘要|与)", t)
    if m:
        return f"{CN_NUM[m.group(2)]}Q{_cn_year(m.group(1))}"
    if re.match(r"^二零二.年与二零二.年的比较|^截至二零二.年[^。]{2,12}止(?:年度|六个月|九个月)与", t):
        return "OTHER"
    return None


class Para:
    __slots__ = ("doc", "idx", "text", "offsets", "page", "bullet", "period", "cells", "heading", "lines")

    def __init__(self, doc, idx, page, bullet, period):
        self.doc, self.idx, self.page, self.bullet, self.period = doc, idx, page, bullet, period
        self.text, self.offsets, self.cells, self.heading, self.lines = "", [], [], False, []

    def line_at(self, pos):
        ln = self.offsets[0][1] if self.offsets else None
        for p, l in self.offsets:
            if p <= pos:
                ln = l
            else:
                break
        return ln

    def draft_text(self):
        """草稿序列化：保留项目符号；表格行写成 '标签 值1 值2 ...'。"""
        t = self.text
        if self.cells:
            t = t + " " + " ".join(self.cells)
        return (self.bullet + " " + t) if self.bullet else t


def _join(a, b, lang):
    if not a:
        return b, 0
    if lang == "en":
        if a.endswith("-") and len(a) > 1 and a[-2].isalpha():
            return a + b, len(a)
        return a + " " + b, len(a) + 1
    if is_cjk(a[-1]) or is_cjk(b[0]) or a[-1] in ",。;:)(、\"'" or b[0] in ",。;:)(、":
        return a + b, len(a)
    return a + " " + b, len(a) + 1


class Doc:
    def __init__(self, q, kind, path=None, lang=None):
        self.q, self.kind = q, kind
        self.lang = lang or LANG.get(kind, "en")
        self.path = Path(path) if path else ensure_text(q, kind)
        self.raw = self.path.read_text(encoding="utf-8").split("\n")
        self.norm = [normalize(x, self.lang) for x in self.raw]
        self.page = []
        pg = 0
        for x in self.raw:
            m = re.match(r"^=== page (\d+) ===$", x)
            if m:
                pg = int(m.group(1))
            self.page.append(pg)
        self.paras = self._paragraphs()

    def _paragraphs(self):
        paras, cur, bullet = [], None, None
        period = self.q
        prose_stop = False

        def flush():
            nonlocal cur
            if cur is not None and (cur.text or cur.cells):
                paras.append(cur)
            cur = None

        for i, t0 in enumerate(self.norm):
            t = t0.strip()
            ln = i + 1
            if t.startswith("=== page"):
                flush()
                continue
            if not t or re.fullmatch(r"(第\s?\d+/\d+页|Page \d+ of \d+|\d{1,3}|- ?\d{1,3} ?-)", t):
                flush()
                continue
            if self.kind.startswith("hkex") and re.match(
                    r"^(CONDENSED CONSOLIDATED INCOME STATEMENT|简明综合收益表)", t):
                prose_stop = True
            if self.kind.startswith("release") and RE_SECTION_STOP.match(t):
                flush()
                period = "OTHER"
                h = Para(self, len(paras), self.page[i], None, period)
                h.text, h.offsets, h.heading, h.lines = t, [(0, ln)], True, [ln]
                paras.append(h)
                continue
            mb = re.match(r"^([▪•‧■●])\s*(\S.*)$", t)
            if mb:
                flush()
                bullet, t = mb.group(1), mb.group(2)
            if self.kind == "ppt" and t in PPT_HEADINGS:
                flush()
                h = Para(self, len(paras), self.page[i], None, period)
                h.text, h.offsets, h.lines = t, [(0, ln)], [ln]
                paras.append(h)
                continue
            hp = heading_period(t, self.lang)
            if hp:
                flush()
                period = hp
                h = Para(self, len(paras), self.page[i], None, period)
                h.text, h.offsets, h.heading, h.lines = t, [(0, ln)], True, [ln]
                paras.append(h)
                continue
            if t in BULLETS:
                flush()
                bullet = t
                continue
            if RE_CELL.match(t) or re.fullmatch(r"(?:[\(\-+]?\d[\d,]*(?:\.\d+)?\)?%?\s+){1,6}[\(\-+]?\d[\d,]*(?:\.\d+)?\)?%?", t):
                if cur is not None and len(cur.text) <= 80 and not cur.text.endswith((".", "。")):
                    cur.cells.extend(t.split())
                    cur.lines.append(ln)
                else:
                    flush()
                continue
            if cur is not None and cur.cells:
                flush()
            if cur is None:
                cur = Para(self, len(paras), self.page[i], bullet, period if not prose_stop else "OTHER")
                bullet = None
            # 行首自带项目符号（如 "▪ Total revenues..."）
            m = re.match(r"^([▪•])\s+(.*)$", t)
            if m and not cur.text:
                cur.bullet, t = m.group(1), m.group(2)
            cur.text, off = _join(cur.text, t, self.lang)
            cur.offsets.append((off, ln))
            cur.lines.append(ln)
        flush()
        for k, p in enumerate(paras):
            p.idx = k
        return paras


_DOC_CACHE = {}


def get_doc(q, kind):
    key = (q, kind)
    if key not in _DOC_CACHE:
        _DOC_CACHE[key] = Doc(q, kind)
    return _DOC_CACHE[key]


# ---------------------------------------------------------------------------
# 5. 指标定义（别名正则 / 表格行标签 / 计算口径）
# ---------------------------------------------------------------------------
GP_HDR = r"Gross profit/\(loss\)|Gross margin"
GP_HDR_ZH = r"毛利/\(毛损\)|毛利率"
RECON_HDR = r"Share-based|As reported|^reported$"
RECON_HDR_ZH = r"股份酬金|如呈报|以股份为基础"


class Metric:
    def __init__(self, mid, zh, en, cls, cat, al_en=(), al_zh=(), tb_en=(), tb_zh=(), pat_en=(), pat_zh=(),
                 calc=None, signed=False, key=False, note="", calc_sum=None):
        self.id, self.zh, self.en, self.cls, self.cat = mid, zh, en, cls, cat
        self.al = {"en": [re.compile(x, re.I) for x in al_en], "zh": [re.compile(x) for x in al_zh]}
        self.al_src = {"en": list(al_en), "zh": list(al_zh)}
        self.tb = {"en": [self._tb(x, re.I) for x in tb_en], "zh": [self._tb(x, 0) for x in tb_zh]}
        self.pat = {"en": [re.compile(x.replace("NUM", NUM), re.I) for x in pat_en],
                    "zh": [re.compile(x.replace("NUM", NUM)) for x in pat_zh]}
        self.calc, self.signed, self.key, self.note = calc, signed, key, note
        self.calc_sum = calc_sum

    @staticmethod
    def _tb(x, flags):
        if isinstance(x, tuple):
            lab, opt = x
        else:
            lab, opt = x, {}
        return (re.compile(lab, flags), opt)


def _m(*a, **k):
    return Metric(*a, **k)


METRICS = [
    _m("rev_total", "总收入", "Total revenues", "RMB", "收入",
       al_en=[r"Total revenues", r"^Revenues:", r"^Revenues(?= (?:increased|decreased|for the|were|grew|rose))"],
       al_zh=[r"总收入", r"^二零二.年第.季的收入(?!成本)"],
       tb_en=[r"Revenues", r"Total Revenue", r"Revenue"], tb_zh=[r"收入"], key=True),
    _m("rev_vas", "增值服务收入", "VAS revenues", "RMB", "收入",
       al_en=[r"Revenues from VAS", r"VAS revenues"],
       al_zh=[r"增值服务业务(?!毛利)", r"增值服务(?=\s?(?:\dQ\d{4}\s?)?收入)"],
       tb_en=[(r"VAS", {"ctx_not": GP_HDR}), r"Value-added Services", r"- VAS"],
       tb_zh=[(r"增值服务", {"ctx_not": GP_HDR_ZH}), r"- 增值服务"], key=True),
    _m("rev_dom_games", "本土市场游戏收入", "Domestic Games revenues", "RMB", "收入",
       al_en=[r"Domestic Games revenues?"], al_zh=[r"本土市场游戏收入"], tb_en=[r"Domestic Games\d?"], key=True),
    _m("rev_intl_games", "国际市场游戏收入", "International Games revenues", "RMB", "收入",
       al_en=[r"International Games revenues?"], al_zh=[r"国际市场游戏收入"], tb_en=[r"International Games"], key=True),
    _m("rev_social", "社交网络收入", "Social Networks revenues", "RMB", "收入",
       al_en=[r"Social Networks revenues?"], al_zh=[r"社交网络收入"], tb_en=[r"Social Networks"], key=True),
    _m("rev_mkt", "营销服务收入", "Marketing Services revenues", "RMB", "收入",
       al_en=[r"Revenues from Marketing Services"],
       al_zh=[r"营销服务业务(?!毛利)", r"营销服务(?=\s?(?:\dQ\d{4}\s?)?收入)"],
       tb_en=[(r"Marketing Services", {"ctx_not": GP_HDR}), r"- Marketing Services"],
       tb_zh=[(r"营销服务", {"ctx_not": GP_HDR_ZH})], key=True),
    _m("rev_fbs", "金融科技及企业服务收入", "FinTech and Business Services revenues", "RMB", "收入",
       al_en=[r"Revenues from FinTech and Business Services"],
       al_zh=[r"金融科技及企业服务业务(?!毛利)", r"金融科技及企业服务(?=\s?(?:\dQ\d{4}\s?)?收入)"],
       tb_en=[(r"FinTech and Business Services", {"ctx_not": GP_HDR}), r"- FinTech and Business Services"],
       tb_zh=[(r"金融科技及企业服务", {"ctx_not": GP_HDR_ZH})], key=True),
    _m("rev_others", "其他收入", "Others revenues", "RMB", "收入",
       tb_en=[(r"Others", {"ctx_not": GP_HDR}), r"- Others"], tb_zh=[(r"其他", {"ctx_not": GP_HDR_ZH})]),
    _m("cost_rev", "收入成本", "Cost of revenues", "RMB", "利润",
       tb_en=[r"Cost of revenues"], tb_zh=[r"收入成本"]),
    _m("gross_profit", "毛利", "Gross profit", "RMB", "利润",
       al_en=[r"Gross profit(?! for (?:VAS|Marketing|FinTech))", r"gross profit:"], al_zh=[r"毛利(?!率)"],
       tb_en=[r"Gross profit", r"Gross Profit"], tb_zh=[r"毛利"], key=True),
    _m("gp_vas", "增值服务毛利", "VAS gross profit", "RMB", "利润",
       al_en=[r"Gross profit for VAS"], al_zh=[r"增值服务业务毛利"],
       tb_en=[(r"VAS", {"ctx": GP_HDR})], tb_zh=[(r"增值服务", {"ctx": GP_HDR_ZH})]),
    _m("gp_mkt", "营销服务毛利", "Marketing Services gross profit", "RMB", "利润",
       al_en=[r"Gross profit for Marketing Services"], al_zh=[r"营销服务业务毛利"],
       tb_en=[(r"Marketing Services", {"ctx": GP_HDR})], tb_zh=[(r"营销服务", {"ctx": GP_HDR_ZH})]),
    _m("gp_fbs", "金融科技及企业服务毛利", "FinTech and Business Services gross profit", "RMB", "利润",
       al_en=[r"Gross profit for FinTech and Business Services"], al_zh=[r"金融科技及企业服务业务毛利"],
       tb_en=[(r"FinTech and Business Services", {"ctx": GP_HDR})], tb_zh=[(r"金融科技及企业服务", {"ctx": GP_HDR_ZH})]),
    _m("sm_exp", "销售及市场推广开支", "Selling and marketing expenses", "RMB", "利润",
       al_en=[r"Selling and marketing expenses"], al_zh=[r"销售及市场推广开支"],
       tb_en=[r"Selling and marketing expenses"], tb_zh=[r"销售及市场推广开支"]),
    _m("ga_exp", "一般及行政开支", "General and administrative expenses", "RMB", "利润",
       al_en=[r"General and administrative expenses"], al_zh=[r"一般及行政开支"],
       tb_en=[r"General and administrative expenses"], tb_zh=[r"一般及行政开支"]),
    _m("opex", "经营开支（销售及市场推广 + 一般及行政）", "Operating expenses (S&M + G&A)", "RMB", "利润",
       tb_en=[r"Operating expenses"], calc_sum=("sm_exp", "ga_exp"),
       note="规范值 = 销售及市场推广开支 + 一般及行政开支（表格百万元口径相加）；PPT 列示为 Operating expenses"),
    _m("other_gains", "其他收益/(亏损)净额", "Other gains/(losses), net", "RMB", "利润",
       tb_en=[r"Other gains/\(losses\),? net"], tb_zh=[r"其他收益/\(亏损\)净额"], signed=True),
    _m("op_profit", "经营盈利（IFRS）", "Operating profit (IFRS)", "RMB", "利润",
       al_en=[r"Operating profit(?!,? excl)"], al_zh=[r"经营盈利"],
       tb_en=[r"Operating profit"], tb_zh=[r"经营盈利"], key=True),
    _m("nonifrs_op", "经营盈利（Non-IFRS）", "Non-IFRS operating profit", "RMB", "利润",
       al_en=[r"Non-IFRS operating profit(?!,? excl)", r"non-IFRS(?:\d)? operating profit:"],
       al_zh=[r"非国际财务报告准则经营盈利", r"按非国际财务报告准则\d?的经营盈利"],
       tb_en=[r"Non-IFRS operating profit"], tb_zh=[r"非国际财务报告准则经营盈利"], key=True),
    _m("nonifrs_op_exai", "经营盈利（Non-IFRS，剔除新AI产品）", "Non-IFRS operating profit excl. new AI products", "RMB", "利润",
       al_en=[r"(?:Non-IFRS )?operating profit,? excl(?:uding|\.) new AI products\d?(?: contributions)?"],
       al_zh=[r"若剔除新\s?AI\s?产品\d?(?:贡献)?,?(?:非国际财务报告准则)?经营盈利"],
       tb_en=[r"Operating Profit excl\. New AI Products\d?"], key=True),
    _m("net_gains_inv", "投资收益/(亏损)净额及其他", "Net gains/(losses) from investments and others", "RMB", "利润",
       tb_en=[r"Net gains/\(losses\) from investments and others", r"Net gains from investments and others"],
       tb_zh=[r"投资收益/\(亏损\)净额及其他"]),
    _m("interest_income", "利息收入", "Interest income", "RMB", "利润",
       al_en=[r"Interest income"], al_zh=[r"利息收入"], tb_en=[r"Interest income"], tb_zh=[r"利息收入"]),
    _m("finance_costs", "财务成本", "Finance costs", "RMB", "利润",
       al_en=[r"Finance costs"], al_zh=[r"财务成本"], tb_en=[r"Finance costs"], tb_zh=[r"财务成本"]),
    _m("share_assoc", "分占联营及合营公司盈利/(亏损)", "Share of profit/(loss) of associates and JVs", "RMB", "利润",
       al_en=[r"share of (?:losses|profits?) of associates and joint ventures"],
       al_zh=[r"分占联营公司及合营公司(?:亏损|盈利)"],
       tb_en=[r"Share of profit/\(loss(?:es)?\) of associates.*"], tb_zh=[r"分占联营公司及合营公司盈利/\(亏损\)净额"],
       signed=True),
    _m("share_assoc_nonifrs", "分占联营及合营公司盈利（Non-IFRS）", "Non-IFRS share of profit of associates and JVs", "RMB", "利润"),
    _m("pbt", "除税前盈利", "Profit before income tax", "RMB", "利润",
       tb_en=[r"Profit before income tax"], tb_zh=[r"除税前盈利"]),
    _m("income_tax", "所得税开支", "Income tax expense", "RMB", "利润",
       al_en=[r"Income tax expense"], al_zh=[r"所得税开支"], tb_en=[r"Income tax expense"], tb_zh=[r"所得税开支"]),
    _m("net_profit", "盈利（IFRS）", "Net profit (IFRS)", "RMB", "利润",
       al_en=[r"Net profit(?! attributable)", r"Profit for the period(?! attributable)"],
       al_zh=[r"(?<![应占营本薄股司内])盈利为", r"期内盈利"],
       tb_en=[r"Profit for the period", r"Net profit"], tb_zh=[r"期内盈利"], key=True),
    _m("nonifrs_np", "盈利（Non-IFRS）", "Non-IFRS net profit", "RMB", "利润",
       tb_en=[(r"Profit for the period", {"col": -1, "ctx": RECON_HDR})],
       tb_zh=[(r"期内盈利", {"col": -1, "ctx": RECON_HDR_ZH})], key=True),
    _m("np_attr", "本公司权益持有人应占盈利（IFRS）", "Profit attributable to equity holders (IFRS)", "RMB", "利润",
       al_en=[r"(?:Net )?profit attributable to equity holders(?: of the Company)?(?: for the (?:period|quarter))?"],
       al_zh=[r"本公司权益持有人(?:应占|归属)盈利"],
       tb_en=[r"Profit attributable to(?: equity(?: holders(?: of the Company)?)?)?",
              r"Net profit attributable to equity holders"],
       tb_zh=[r"本公司权益持有人(?:应占|归属)盈利"], key=True),
    _m("nonifrs_np_attr", "本公司权益持有人应占盈利（Non-IFRS）", "Non-IFRS profit attributable to equity holders", "RMB", "利润",
       al_en=[r"Non-IFRS profit attributable to equity holders(?: of the Company)?"],
       al_zh=[r"非国际财务报告准则本公司权益持有人(?:应占|归属)盈利"],
       tb_en=[r"Non-IFRS profit attributable to(?: equity)?(?: holders)?(?: of the Company)?",
              (r"Profit attributable to(?: equity(?: holders(?: of the Company)?)?)?", {"col": -1, "ctx": RECON_HDR})],
       tb_zh=[r"非国际财务报告准则本公司(?:权益持有人应占盈利)?",
              (r"本公司权益持有人应占盈利", {"col": -1, "ctx": RECON_HDR_ZH})], key=True),
    _m("eps_basic", "每股基本盈利（IFRS）", "Basic EPS (IFRS)", "RMB1", "每股",
       al_en=[r"Basic earnings per share"], al_zh=[r"每股基本盈利"],
       tb_en=[(r"- ?basic", {"eps": True})], tb_zh=[(r"- ?基本", {"eps": True})]),
    _m("eps_diluted", "每股摊薄盈利（IFRS）", "Diluted EPS (IFRS)", "RMB1", "每股",
       al_en=[r"Diluted earnings per share", r"Diluted EPS(?: in RMB)?"], al_zh=[r"每股摊薄盈利"],
       tb_en=[(r"- ?diluted", {"eps": True}), r"Diluted EPS in RMB"], tb_zh=[(r"- ?摊薄", {"eps": True})], key=True),
    _m("nonifrs_eps_basic", "每股基本盈利（Non-IFRS）", "Non-IFRS basic EPS", "RMB1", "每股"),
    _m("nonifrs_eps_diluted", "每股摊薄盈利（Non-IFRS）", "Non-IFRS diluted EPS", "RMB1", "每股", key=True),
    _m("capex", "资本开支（会计口径，单季）", "Capital expenditures", "RMB", "资本开支",
       al_en=[r"Capital expenditures?(?! payments| primarily| consist)"], al_zh=[r"资本开支(?!付款)"],
       tb_en=[r"Capital expenditures(?: \(d\))?", r"Total CAPEX"], tb_zh=[r"资本开支(?: ?\(d\))?"], key=True),
    _m("capex_op", "经营性资本开支", "Operating CAPEX", "RMB", "资本开支", tb_en=[r"Operating CAPEX"]),
    _m("capex_nonop", "非经营性资本开支", "Non-operating CAPEX", "RMB", "资本开支", tb_en=[r"Non-operating CAPEX"]),
    _m("capex_pay", "资本开支付款（现金，单季）", "Capital expenditure payments", "RMB", "资本开支",
       al_en=[r"capital expenditure payments", r"payments for capital expenditures?(?: of)?"],
       al_zh=[r"资本开支付款", r"资本开支付款项"], key=True),
    _m("fcf", "自由现金流", "Free cash flow", "RMB", "现金流",
       al_en=[r"free cash flow(?! would| generation)"], al_zh=[r"自由现金流(?=\s?(?:为|转负|人民币))"], tb_en=[r"Free Cash Flow"],
       signed=True, key=True),
    _m("fcf_ex_prepay", "自由现金流（剔除算力预付款）", "FCF excl. compute prepayments", "RMB", "现金流",
       al_en=[r"Excluding the prepayments for compute procurement, our free cash flow(?: would have been)?"],
       al_zh=[r"若剔除算力采购的预付款项,?我们的自由现金流"], key=True),
    _m("ocf", "经营活动现金净额", "Net cash from operating activities", "RMB", "现金流",
       al_en=[r"net cash generated from operating activities"], al_zh=[r"经营现金流(?!包括)", r"经营活动所产生的现金净额"]),
    _m("media_pay", "媒体内容付款", "Media content payments", "RMB", "现金流",
       al_en=[r"media content payments"], al_zh=[r"媒体内容付款"]),
    _m("lease_pay", "租赁负债付款", "Lease liability payments", "RMB", "现金流",
       al_en=[r"lease liability payments"], al_zh=[r"租赁负债付款"]),
    _m("total_cash", "总现金", "Total cash", "RMB", "资产负债",
       al_en=[r"Total cash"], al_zh=[r"总现金"], tb_en=[r"Total Cash"], key=True),
    _m("net_cash", "净现金", "Net cash", "RMB", "资产负债",
       al_en=[r"Net cash position(?: totalled)?", r"had net cash of", r"Net cash(?= (?:was|totalled|of))"],
       al_zh=[r"净现金", r"现金净额(?=为)"], tb_en=[r"Net cash(?: \(c\))?", r"Net Cash"], tb_zh=[r"现金净额(?: ?\(c\))?"],
       key=True),
    _m("total_debt", "总债务", "Total debt", "RMB", "资产负债", tb_en=[r"Less: Total Debt"]),
    _m("ebitda", "EBITDA", "EBITDA", "RMB", "利润", tb_en=[r"EBITDA(?: \(a\))?"], tb_zh=[r"EBITDA ?(?:\(a\))?"]),
    _m("adj_ebitda", "经调整 EBITDA", "Adjusted EBITDA", "RMB", "利润",
       tb_en=[r"Adjusted EBITDA(?: \(a\))?"], tb_zh=[r"经调整 ?EBITDA ?(?:\(a\))?"]),
    _m("listed_fv", "上市投资公司权益公允价值", "Fair value of listed investees", "RMB", "资产负债",
       al_en=[r"fair value of (?:our )?shareholdings\d? in listed investee companies(?: \(excluding subsidiaries\))?"],
       al_zh=[r"(?<!非)上市投资公司\(不包括附属公司\)权益\d?的公允价值\d?"]),
    _m("unlisted_bv", "非上市投资公司权益账面价值", "Carrying value of unlisted investees", "RMB", "资产负债",
       al_en=[r"carrying book value of (?:our )?shareholdings\d? in unlisted investee companies(?: \(excluding subsidiaries\))?"],
       al_zh=[r"非上市投资公司\(不包括附属公司\)权益\d?的账面价值"]),
    _m("buyback_shares", "季度回购股数", "Shares repurchased in quarter", "count", "股东回报",
       al_en=[r"repurchased approximately", r"Repurchased ~?"], pat_zh=[r"回购约?\s?(?P<v>NUM\s?万)股"]),
    _m("buyback_hkd", "季度回购总代价（港元）", "Buyback consideration (HKD)", "HKD", "股东回报",
       al_en=[r"aggregate consideration of"], pat_zh=[r"以(?P<v>约?\s?NUM\s?亿港元)的总代价"]),
    _m("buyback_rmb", "季度回购总代价（人民币，PPT口径）", "Buyback consideration (RMB, PPT)", "RMB", "股东回报",
       al_en=[r"for a consideration of"]),
    _m("dividend_paid", "本季派付股息", "Dividend paid in quarter", "RMB", "股东回报",
       al_en=[r"paid cash dividend of", r"dividend payments of"], al_zh=[r"股息支付", r"股息派付"]),
    _m("mau_weixin", "微信及WeChat合并月活跃账户数", "Combined MAU of Weixin and WeChat", "count", "运营",
       al_en=[r"Combined MAU of Weixin and WeChat", r"(?<!devices )(?<!device )MAU at(?= ?[\d,]+ ?m)"], al_zh=[r"微信及\s?WeChat\s?的\s?合并月活跃账户数"],
       tb_en=[r"Combined MAU of Weixin(?: and WeChat)?"], tb_zh=[r"微信及\s?WeChat\s?的(?:\s?合并月活跃账户数)?"], key=True),
    _m("mau_qq", "QQ移动终端月活跃账户数", "Mobile device MAU of QQ", "count", "运营",
       al_en=[r"Mobile devices? MAU of QQ", r"Mobile devices? MAU at"], al_zh=[r"QQ\s?的移动终端月活跃账户数"],
       tb_en=[r"Mobile device MAU of QQ"], tb_zh=[r"QQ\s?的移动终端月活跃账户数"], key=True),
    _m("vas_subs", "收费增值服务订阅数", "Fee-based VAS subscriptions", "count", "运营",
       al_en=[r"Fee-based VAS subscriptions\d?"], al_zh=[r"收费增值服务订阅会员数\d?"],
       tb_en=[r"Fee-based VAS subscriptions\d?#?"], tb_zh=[r"收费增值服务订阅会员数\d?#?"], key=True),
    _m("gross_margin", "毛利率", "Gross margin", "pct", "利润率",
       al_en=[r"Gross margin(?! for)"], al_zh=[r"毛利率"], tb_en=[r"Gross margin"], tb_zh=[r"毛利率"],
       calc=("gross_profit", "rev_total")),
    _m("gm_vas", "增值服务毛利率", "VAS gross margin", "pct", "利润率", calc=("gp_vas", "rev_vas")),
    _m("gm_mkt", "营销服务毛利率", "Marketing Services gross margin", "pct", "利润率", calc=("gp_mkt", "rev_mkt")),
    _m("gm_fbs", "金融科技及企业服务毛利率", "FBS gross margin", "pct", "利润率", calc=("gp_fbs", "rev_fbs")),
    _m("op_margin", "经营利润率（IFRS）", "Operating margin (IFRS)", "pct", "利润率",
       al_en=[r"Operating margin(?!,? excl)"], al_zh=[r"经营利润率"],
       tb_en=[r"Operating margin"], tb_zh=[r"经营利润率"], calc=("op_profit", "rev_total")),
    _m("nonifrs_op_margin", "经营利润率（Non-IFRS）", "Non-IFRS operating margin", "pct", "利润率",
       tb_en=[(r"Operating margin", {"col": -1, "ctx": RECON_HDR})], tb_zh=[(r"经营利润率", {"col": -1, "ctx": RECON_HDR_ZH})],
       calc=("nonifrs_op", "rev_total"), key=True),
    _m("op_margin_exai", "经营利润率（Non-IFRS，剔除新AI产品）", "Non-IFRS operating margin excl. new AI products", "pct", "利润率",
       al_en=[r"Operating margin,? excl(?:uding|\.) new AI products(?: contributions)?"],
       al_zh=[r"若剔除新\s?AI\s?产品\d?(?:贡献)?,?经营利润率"], key=True,
       note="分母口径未披露（可能剔除新AI产品收入），故不做计算核对，仅比对各文件表述"),
    _m("adj_ebitda_margin", "经调整 EBITDA 利润率", "Adjusted EBITDA margin", "pct", "利润率",
       tb_en=[r"Adjusted EBITDA margin(?: \(b\))?"], tb_zh=[r"经调整 ?EBITDA ?利润率(?: ?\(b\))?"],
       calc=("adj_ebitda", "rev_total")),
]
MET = {m.id: m for m in METRICS}
NONIFRS_REMAP = {"op_profit": "nonifrs_op", "net_profit": "nonifrs_np", "np_attr": "nonifrs_np_attr",
                 "eps_basic": "nonifrs_eps_basic", "eps_diluted": "nonifrs_eps_diluted",
                 "op_margin": "nonifrs_op_margin", "share_assoc": "share_assoc_nonifrs"}
SUBJECT_REMAP = {"gross_margin": {"gp_vas": "gm_vas", "gp_mkt": "gm_mkt", "gp_fbs": "gm_fbs"}}
PPT_HEADINGS = {"Social Networks": "rev_social", "Domestic Games": "rev_dom_games",
                "International Games": "rev_intl_games", "Marketing Services": "rev_mkt", "Overall": None,
                "FinTech Services": "", "Business Services": "", "Weixin": "", "Video Accounts": "", "Mini Shops": ""}
# 勾稽关系：左边 = 右边各项之和（'-' 表示减项）
RELATIONS = [
    ("rev_vas", ["rev_dom_games", "rev_intl_games", "rev_social"]),
    ("rev_total", ["rev_vas", "rev_mkt", "rev_fbs", "rev_others"]),
    ("capex", ["capex_op", "capex_nonop"]),
    ("net_cash", ["total_cash", "-total_debt"]),
    ("fcf", ["ocf", "-capex_pay", "-media_pay", "-lease_pay"]),
]

# ---------------------------------------------------------------------------
# 6. 句子级抽取：别名 → 紧随其后的数值 / 同比环比
# ---------------------------------------------------------------------------
RE_GROWTH_EN = re.compile(
    r"(?P<dir>up|down|increased by|decreased by|increased|decreased|rose by|rose|grew by|grew|declined by|declined|"
    r"fell by|fell|dropped by|growth of|increase of|decrease of)\s+(?:approximately\s|over\s|more than\s)?"
    r"(?P<num>\d+(?:\.\d+)?)\s?%", re.I)
RE_GROWTH_EN_SIGNED = re.compile(r"(?<![\w.])(?P<sign>[+\-])(?P<num>\d+(?:\.\d+)?)\s?%\s?(?P<kind>YoY|QoQ)", re.I)
RE_GROWTH_ZH = re.compile(r"(?P<kind>同比|环比)?\s?(?P<dir>增长|增加|上升|提升|下降|减少|下跌|下滑)\s?(?:了\s?)?(?:超过|逾|约|近)?\s?(?P<num>\d+(?:\.\d+)?)\s?%")
DOWN_WORDS = ("down", "decreas", "declin", "fell", "dropped", "下降", "减少", "下跌", "下滑")
RE_SKIP_PERIOD = re.compile(r"six months|first half|full year|for the year|in the year|during the year|nine months|annual|"
                            r"上半年|六个月|九个月|全年|年内|"
                            r"(?<![零一二三四五六七八九\d])年度",
                            re.I)
RE_FROM_TO_ZH = re.compile(r"由[^%。;]{0,12}?(?P<a>\d+(?:\.\d+)?)\s?%\s?(?:上升|提升|下降|增加|减少|扩大|收窄|改善)至\s?"
                           r"(?P<b>\d+(?:\.\d+)?)\s?%")
# 别名与数值之间出现这些因果/抵销连接词时，数值属于另一事项，不作关联
RE_BREAK = re.compile(r"offset by|due to|primarily reflecting|mainly reflecting|部分被|主要由于|主要反映|乃由于", re.I)
RE_PRIOR_PREFIX = re.compile(r"compared (?:with|to)\s*$|日的\s*$|去年同期的\s*$|上季的\s*$", re.I)
RE_FROM_EN = re.compile(r"from\s(?P<a>\d+(?:\.\d+)?)\s?%")


class Growth:
    __slots__ = ("kind", "value", "half", "raw", "start", "end")

    def __init__(self, kind, value, half, raw, start, end):
        self.kind, self.value, self.half, self.raw, self.start, self.end = kind, value, half, raw, start, end

    def as_dict(self):
        return {"kind": self.kind, "value": self.value, "half": self.half, "raw": self.raw}


def parse_growths(text, lang):
    out = []
    if lang == "en":
        for m in RE_GROWTH_EN.finditer(text):
            v, dec = _numval(m.group("num"))
            if any(w in m.group("dir").lower() for w in DOWN_WORDS):
                v = -v
            tail = text[m.end():m.end() + 60]
            kind = "qoq" if re.search(r"^[^.;]*?(quarter-on-quarter|QoQ|previous quarter|sequential)", tail, re.I) else "yoy"
            out.append(Growth(kind, v, 0.5 * 10 ** -dec, m.group(0), m.start(), m.end()))
        for m in RE_GROWTH_EN_SIGNED.finditer(text):
            v, dec = _numval(m.group("num"))
            if m.group("sign") == "-":
                v = -v
            out.append(Growth(m.group("kind").lower(), v, 0.5 * 10 ** -dec, m.group(0), m.start(), m.end()))
    else:
        for m in RE_GROWTH_ZH.finditer(text):
            v, dec = _numval(m.group("num"))
            if any(w in m.group("dir") for w in DOWN_WORDS):
                v = -v
            kind = m.group("kind")
            if not kind:
                pre = text[max(0, m.start() - 10):m.start()]
                kind = "环比" if "环比" in pre else "同比"
            out.append(Growth("qoq" if kind == "环比" else "yoy", v, 0.5 * 10 ** -dec, m.group(0), m.start(), m.end()))
    out.sort(key=lambda g: g.start)
    return out


def split_clauses(text, lang):
    """切句：英文按 '. '（其后为大写/引号/数字）与 ';'，中文按 '。' ';'。返回 [(start, end)]。"""
    if lang == "en":
        cuts = [m.end() for m in re.finditer(r"(?<!\be\.g)(?<!\bi\.e)(?<!\bNo)(?<!\bapprox)\.\s+(?=[A-Z\"'(~\d])|;\s*", text)]
    else:
        cuts = [m.end() for m in re.finditer(r"[。;!]", text)]
    out, s = [], 0
    for c in cuts:
        if c > s:
            out.append((s, c))
        s = c
    if s < len(text):
        out.append((s, len(text)))
    return out


class Claim:
    __slots__ = ("metric", "num", "growth", "prior", "kind", "para", "a_start", "a_end", "line", "mode", "cells",
                 "quote", "period_ok", "basis", "col", "page", "text")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class Ctx:
    def __init__(self):
        self.basis = None
        self.heading_metric = None


def find_aliases(clause, lang):
    cands = []
    for m in METRICS:
        for rx in m.pat[lang]:
            for mm in rx.finditer(clause):
                cands.append((mm.start(), mm.end(), m.id, "pat", mm))
        for rx in m.al[lang]:
            for mm in rx.finditer(clause):
                if mm.end() > mm.start():
                    cands.append((mm.start(), mm.end(), m.id, "al", mm))
    if lang == "en":
        for mm in re.finditer(r"^Revenue(?= (?:was|grew|increased|decreased|rose|declined))", clause):
            cands.append((mm.start(), mm.end(), "__heading__", "al", mm))
    cands.sort(key=lambda c: (c[0], -(c[1] - c[0]), 0 if c[3] == "pat" else 1))
    sel, last_end = [], -1
    for c in cands:
        if c[0] >= last_end:
            sel.append(c)
            last_end = c[1]
    return sel


def _sign_word(prefix, window, lang):
    """FCF 等带符号指标：从别名前后的措辞判断正负（negative / 负 / 转负）。"""
    if lang == "en":
        if "negative" in prefix[-14:].lower():
            return -1
    elif "负" in prefix[-3:] or window.lstrip().startswith("转负"):
        return -1
    return 1


def parse_para(para_text, lang, ctx, bullet=None, cells=None, subject_reset=True):
    """对一个段落做确定性抽取，返回 Claim 列表（未填 doc/line）。"""
    claims = []
    text = para_text
    # 口径状态（Non-IFRS / IFRS）：标记段落设置；仅在后续 '-' 子条目中延续
    if re.match(r"\W*On a non-IFRS\d? basis|\W*按非国际财务报告准则\d?,", text, re.I):
        ctx.basis = "nonifrs"
    elif re.match(r"\W*On an IFRS basis|\W*按国际财务报告准则\d?:", text):
        ctx.basis = "ifrs"
    elif bullet != "-":
        ctx.basis = None
    # PPT 小标题（如 "Social Networks"）
    if lang == "en" and text.strip() in PPT_HEADINGS:
        h = PPT_HEADINGS[text.strip()]
        if h is not None:
            ctx.heading_metric = h or None
    last_metric = None
    # 表格行模式：标签 + ≥3 个数值
    if cells and len(cells) >= 2:
        for (s, e, mid, typ, mm) in reversed(find_aliases(text, lang)):
            met = MET.get(mid)
            if not met:
                continue
            c0 = parse_cell(cells[0])
            if c0 is None or c0[0] == "pct" and met.cls != "pct":
                continue
            v = c0[1]
            num = Num(met.cls, abs(v) if not met.signed else v, c0[2], cells[0], len(text) + 1,
                      len(text) + 1 + len(cells[0]), token=cells[0].strip("()+-"))
            gr = []
            if len(cells) >= 5:
                for kind, idx in (("yoy", 2), ("qoq", 4)):
                    cc = parse_cell(cells[idx])
                    if cc and cc[0] == "pct":
                        gr.append(Growth(kind, cc[1], cc[2], cells[idx], 0, 0))
            claims.append(Claim(metric=mid, num=num, growth=gr, prior=None, a_start=s, a_end=e, mode="row",
                                cells=list(cells), period_ok=True, basis=None))
            break
        return claims
    for (cs, ce) in split_clauses(text, lang):
        clause = text[cs:ce]
        skip = bool(RE_SKIP_PERIOD.search(clause) or RE_SKIP_SCOPE.search(clause))
        aliases = find_aliases(clause, lang)
        if not aliases:
            continue
        nums = parse_numbers(clause, lang)
        growths = parse_growths(clause, lang)
        for i, (s, e, mid, typ, mm) in enumerate(aliases):
            wend = aliases[i + 1][0] if i + 1 < len(aliases) else len(clause)
            if mid == "__heading__":
                mid = ctx.heading_metric
                if not mid:
                    continue
            prefix = clause[:s]
            if RE_PRIOR_PREFIX.search(prefix):
                continue
            if mid in NONIFRS_REMAP and (ctx.basis == "nonifrs" or re.search(r"non-IFRS[^.;]{0,25}$|非国际财务报告准则[^。;]{0,6}$|non-IFRS basis",
                                                                           prefix, re.I)):
                mid = NONIFRS_REMAP[mid]
            if mid in SUBJECT_REMAP and last_metric in SUBJECT_REMAP[mid]:
                mid = SUBJECT_REMAP[mid][last_metric]
            met = MET[mid]
            num = None
            prior = None
            if typ == "pat":
                vt = mm.group("v")
                pn = parse_numbers(vt, lang) or parse_numbers(vt + "元", lang)
                if pn:
                    n0 = pn[0]
                    n0.start += mm.start("v") + cs
                    n0.end = mm.end("v") + cs
                    if met.cls == "count" and n0.cls == "RMB":
                        n0.cls = "count"
                    num = n0
            elif met.cls == "pct":
                win = clause[e:wend]
                ft = RE_FROM_TO_ZH.search(win) if lang == "zh" else None
                if ft and ft.start() < 4:
                    b = ft.group("b")
                    v, dec = _numval(b)
                    num = Num("pct", v, 0.5 * 10 ** -dec, b + "%", cs + e + ft.start("b"), cs + e + ft.end(), token=b, dec=dec)
                    a = ft.group("a")
                    va, deca = _numval(a)
                    prior = Num("pct", va, 0.5 * 10 ** -deca, a + "%", cs + e + ft.start("a"), cs + e + ft.start("a") + len(a) + 1,
                                token=a, dec=deca)
                else:
                    for n in nums:
                        if e < n.end <= wend and n.cls == "pct":
                            num = Num(n.cls, n.value, n.half, n.raw, n.start + cs, n.end + cs, token=n.token, dec=n.dec)
                            break
                    if num is not None:
                        fm = RE_FROM_EN.search(clause, num.end - cs, wend) if lang == "en" else None
                        if fm:
                            va, deca = _numval(fm.group("a"))
                            prior = Num("pct", va, 0.5 * 10 ** -deca, fm.group("a") + "%", fm.start("a") + cs,
                                        fm.end() + cs, token=fm.group("a"), dec=deca)
            else:
                want = MONEY_CLS if met.cls in MONEY_CLS else {met.cls}
                cand = [n for n in nums if e < n.end <= wend and n.cls in want
                        and not RE_BREAK.search(clause[e:n.start])]
                if cand:
                    n = cand[0]
                    # "由 X 增加至 Y" / "from X to Y"：取变动后的 Y
                    if len(cand) > 1 and re.search(r"由|from\s", clause[e:n.start]) and \
                            re.search(r"至\s?$|\bto\s?$", clause[n.end:cand[1].start]):
                        n = cand[1]
                    num = Num(n.cls, n.value, n.half, n.raw, n.start + cs, n.end + cs, n.approx, n.token, n.dec)
                if num is not None and met.signed:
                    sg = _sign_word(clause[:s], clause[e:wend], lang)
                    if lang == "en" and met.id == "share_assoc":
                        sg = -1 if "losses" in clause[s:e].lower() else 1
                    if lang == "zh" and met.id == "share_assoc":
                        sg = -1 if "亏损" in clause[s:e] else 1
                    num.value = sg * abs(num.value)
            gr = []
            for g in growths:
                if g.start >= e and g.start < wend:
                    gr.append(Growth(g.kind, g.value, g.half, g.raw, g.start + cs, g.end + cs))
                    break
            if num is None and not gr:
                continue
            last_metric = mid
            claims.append(Claim(metric=mid, num=num, growth=gr, prior=prior, a_start=s + cs, a_end=e + cs, mode="prose",
                                period_ok=not skip, basis=ctx.basis))
    return claims


def parse_cell(c):
    c = c.strip()
    if re.fullmatch(r"(?:stable|稳定|持平)", c, re.I):
        return ("pct", 0.0, 0.5, 0)
    if re.fullmatch(r"(?:NA|NM|N/A|-|不适用)", c, re.I):
        return None
    m = re.fullmatch(r"(?P<neg>\()?(?P<sign>[+\-])?(?P<num>\d[\d,]*(?:\.\d+)?)\)?\s?(?P<unit>%|ppt)?", c)
    if not m:
        return None
    v, dec = _numval(m.group("num"))
    if m.group("neg") or m.group("sign") == "-":
        v = -v
    unit = m.group("unit")
    return ("pct" if unit == "%" else "ppt" if unit == "ppt" else "num", v, 0.5 * 10 ** -dec, dec)


# ---------------------------------------------------------------------------
# 7. 表格行（标签 + 数值单元格）抽取：用于注册表与勾稽矩阵
# ---------------------------------------------------------------------------
RE_UNIT_HDR = re.compile(r"RMB in millions|RMB'Million|RMB Million|In billion RMB|billion RMB|人民币百万元|百万计|"
                         r"in millions|RMB'000|人民币千元", re.I)
RE_PERIOD_HDR = re.compile(r"Three months ended|Six months ended|Year ended|Nine months ended|止三个月|止六个月|止年度|"
                           r"止九个月", re.I)


def is_cell(t):
    return bool(RE_CELL.match(t))


def table_rows(doc):
    """返回 [(label_variants, cells(list[str]), cell_line_idx(list))]；label_variants 为末 1/2/3 行拼接。"""
    rows, n, i = [], len(doc.norm), 0
    while i < n:
        t = doc.norm[i].strip()
        if not t or is_cell(t) or t.startswith("=== page"):
            i += 1
            continue
        lab = [i]
        j = i + 1
        while j < n and len(lab) < 3:
            tj = doc.norm[j].strip()
            if not tj or is_cell(tj) or tj.startswith("=== page"):
                break
            lab.append(j)
            j += 1
        if j < n and is_cell(doc.norm[j].strip()):
            cells, cl = [], []
            k = j
            while k < n and is_cell(doc.norm[k].strip()):
                cells.append(doc.norm[k].strip())
                cl.append(k)
                k += 1
            texts = [doc.norm[x].strip() for x in lab]
            variants = []
            for w in (1, 2, 3):
                if w <= len(texts):
                    sub = texts[-w:]
                    joined = sub[0]
                    for s2 in sub[1:]:
                        joined = _join(joined, s2, doc.lang)[0]
                    variants.append((joined, lab[-w:]))
            rows.append((variants, cells, cl))
            i = k
            continue
        i += 1
    return rows


def _lookback(doc, start, pat, limit=80):
    for x in range(start - 1, max(-1, start - limit), -1):
        if pat.search(doc.norm[x]):
            return x
    return None


def table_claims(doc):
    out = []
    lang = doc.lang
    for variants, cells, cl in table_rows(doc):
        anchor = variants[0][1][0]          # 紧挨数值的标签行
        u = _lookback(doc, anchor + 1, RE_UNIT_HDR, 90)
        scale = 1.0
        if u is not None and re.search(r"billion", doc.norm[u], re.I):
            scale = 1000.0
        elif u is None and doc.kind == "ppt":
            scale = 1000.0
        hdr_lo = max(0, (u if u is not None else anchor) - 16)
        header = "\n".join(doc.norm[hdr_lo:anchor])
        hdr_ctx = chr(10).join(doc.norm[max(0, (u if u is not None else anchor) - 30):anchor])
        per = RE_PERIOD_HDR.findall(header)
        period_ok = True
        if per and not any(re.search(r"Three months|三个月", p, re.I) for p in per):
            period_ok = False
        basis = None
        if doc.kind == "ppt":   # PPT 表内以单独一行 "Non-IFRS" 分隔口径
            between = [doc.norm[x].strip() for x in range(u + 1 if u is not None else max(0, anchor - 30), anchor)]
            if any(re.fullmatch(r"Non-IFRS", b) for b in between):
                basis = "nonifrs"
        used_cols = set()
        for lab_text, lab_lines in reversed(variants):      # 先试最长标签（应对跨行标签）
            lt = re.sub(r"\s*(?:\(\w\)|#|\d)$", "", lab_text).strip()
            for m in METRICS:
                for rx, opt in m.tb[lang]:
                    col = opt.get("col", 0)
                    if col in used_cols:
                        continue
                    if not (rx.fullmatch(lt) or rx.fullmatch(lab_text)):
                        continue
                    if opt.get("ctx") and not re.search(opt["ctx"], hdr_ctx, re.I | re.M):
                        continue
                    if opt.get("ctx_not") and re.search(opt["ctx_not"], hdr_ctx, re.I | re.M):
                        continue
                    mid = m.id
                    rb = basis
                    if opt.get("eps"):
                        e = _lookback(doc, lab_lines[0], re.compile(r"EPS|earnings per share|每股盈利", re.I), 16)
                        rb = "nonifrs" if e is not None and re.search(r"Non-IFRS|非国际", doc.norm[e], re.I) else "ifrs"
                    if re.match(r"Non-IFRS|非国际", lt, re.I):
                        rb = "nonifrs"
                    if col == 0 and rb == "nonifrs" and mid in NONIFRS_REMAP:
                        mid = NONIFRS_REMAP[mid]
                    met = MET[mid]
                    cc = list(cells)
                    if len(cc) >= 3 and re.fullmatch(r"\d{1,2}", cc[0]) and met.cls not in ("pct", "count"):
                        cc = cc[1:]
                    if col == -1 and len(cc) < 2:
                        continue
                    pc = parse_cell(cc[col]) if cc else None
                    if pc is None:
                        continue
                    if met.cls == "pct" and pc[0] != "pct":
                        continue
                    if met.cls != "pct" and pc[0] != "num":
                        continue
                    if met.cls in ("RMB", "HKD", "USD"):
                        val, half = pc[1] * scale, pc[2] * scale
                    else:
                        val, half = pc[1], pc[2]
                    if not met.signed:
                        val = abs(val)
                    num = Num(met.cls, val, half, cc[col], 0, 0, token=cc[col].strip("()+-%"), dec=pc[3])
                    gr = []
                    if col == 0 and len(cc) >= 5:
                        c1, c2, c3, c4 = (parse_cell(cc[x]) for x in (1, 2, 3, 4))
                        if c1 and c1[0] == "num" and c2 and c2[0] == "pct" and c3 and c3[0] == "num" and c4 and c4[0] == "pct":
                            gr = [Growth("yoy", c2[1], c2[2], cc[2], 0, 0), Growth("qoq", c4[1], c4[2], cc[4], 0, 0)]
                    off = len(cells) - len(cc)
                    ln = cl[off + (col if col >= 0 else len(cc) + col)] + 1
                    out.append(Claim(metric=mid, num=num, growth=gr, prior=None, kind=doc.kind, para=None, a_start=0,
                                     a_end=0, line=ln, mode="table", cells=cc, period_ok=period_ok, basis=rb, col=col,
                                     page=doc.page[ln - 1], quote=lab_text + " | " + " | ".join(cells), text=lab_text))
                    used_cols.add(col)
                    break
            if used_cols:
                break
    return out


def prose_claims(doc, q):
    out = []
    ctx = Ctx()
    last_page = None
    for p in doc.paras:
        if p.page != last_page:
            ctx.heading_metric = None
            last_page = p.page
        if p.heading:
            continue
        if p.cells:
            ctx.basis = None
            continue
        cl = parse_para(p.text, doc.lang, ctx, p.bullet)
        if p.period != q:
            continue
        for c in cl:
            pos = c.num.start if c.num is not None else (c.growth[0].start if c.growth else c.a_start)
            c.kind, c.para = doc.kind, p.idx
            c.line = p.line_at(pos)
            c.page = doc.page[c.line - 1] if c.line else p.page
            c.quote = doc.raw[c.line - 1].strip() if c.line else ""
            c.text = p.text
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# 8. 注册表：多文件取值 → 聚类取共识 → 规范值（最精确者）
# ---------------------------------------------------------------------------
KIND_PREF = {"hkex_en": 0, "hkex_zh": 1, "release_en": 2, "release_zh": 3, "ppt": 4}


def cval(m, num):
    return num.value if m.signed else abs(num.value)


def _cluster(items):
    """items: [(value, half, claim)] → 按四舍五入区间一致性聚类（以最精确者为代表）。"""
    items = sorted(items, key=lambda x: (x[1], KIND_PREF.get(x[2].kind, 9), x[2].line or 0))
    clusters = []
    for it in items:
        for cl in clusters:
            if consistent(cl[0][0], cl[0][1], it[0], it[1]):
                cl.append(it)
                break
        else:
            clusters.append([it])
    return clusters


def _best(clusters):
    def score(cl):
        hk_table = any(x[2].mode == "table" and x[2].kind.startswith("hkex") for x in cl)
        return (hk_table, len(set(x[2].kind for x in cl)), len(cl), -cl[0][1])
    return max(clusters, key=score) if clusters else None


def collect_claims(q, kinds):
    allc = {}
    for kind in kinds:
        doc = get_doc(q, kind)
        for c in prose_claims(doc, q) + table_claims(doc):
            allc.setdefault(c.metric, []).append(c)
    return allc


def build_registry(q, kinds):
    allc = collect_claims(q, kinds)
    reg = {}
    for m in METRICS:
        cl = allc.get(m.id, [])
        vals = [(cval(m, c.num), c.num.half, c) for c in cl
                if c.num is not None and c.period_ok and c.num.cls == m.cls]
        e = {"id": m.id, "zh": m.zh, "en": m.en, "cls": m.cls, "cat": m.cat, "key": m.key, "claims": cl, "q": q}
        if (m.calc is None and m.calc_sum is None) or m.id == "op_margin_exai":
            best = _best(_cluster(vals))
            if best:
                rep = best[0]
                e.update(value=rep[0], half=rep[1], src=rep[2], support=sorted(set(x[2].kind for x in best)),
                         n=len(best), calc=False)
        for kind_g in ("yoy", "qoq"):
            gv = []
            for c in cl:
                if not c.period_ok:
                    continue
                for g in c.growth or []:
                    if g.kind == kind_g:
                        gv.append((g.value, g.half, c))
            best = _best(_cluster(gv))
            if best:
                e[kind_g] = {"value": best[0][0], "half": best[0][1], "src": best[0][2],
                             "support": sorted(set(x[2].kind for x in best))}
        reg[m.id] = e
    for m in METRICS:
        if m.calc_sum and "value" not in reg[m.id] and all("value" in reg.get(x, {}) for x in m.calc_sum):
            reg[m.id].update(value=sum(reg[x]["value"] for x in m.calc_sum),
                             half=sum(reg[x]["half"] for x in m.calc_sum), src=None, support=[], n=0, calc=True,
                             calc_from=list(m.calc_sum))
    for m in METRICS:
        if m.calc and "value" not in reg[m.id]:
            a, b = reg.get(m.calc[0], {}), reg.get(m.calc[1], {})
            if "value" in a and "value" in b and b["value"]:
                lo = (a["value"] - a["half"]) / (b["value"] + b["half"]) * 100
                hi = (a["value"] + a["half"]) / (b["value"] - b["half"]) * 100
                reg[m.id].update(value=(lo + hi) / 2, half=(hi - lo) / 2, src=None, support=[], n=0, calc=True,
                                 calc_from=list(m.calc))
    return reg


def attach_priors(regs):
    """同比/环比参照：上年同季、上一季的规范值（来自各自季度的注册表）。"""
    for q, reg in regs.items():
        for mid, e in reg.items():
            for key, pq in (("prior_y", PREV_Y.get(q)), ("prior_q", PREV_Q.get(q))):
                if pq and pq in regs and "value" in regs[pq].get(mid, {}) and "value" in e:
                    p = regs[pq][mid]
                    e[key] = {"q": pq, "value": p["value"], "half": p["half"]}
                    if MET[mid].cls != "pct" and p["value"] and abs(p["value"]) > p["half"]:
                        r1 = (e["value"] - e["half"]) / (p["value"] + p["half"])
                        r2 = (e["value"] + e["half"]) / (p["value"] - p["half"])
                        lo, hi = sorted(((r1 - 1) * 100, (r2 - 1) * 100))
                        e[key + "_growth"] = {"value": (lo + hi) / 2, "half": (hi - lo) / 2}
    return regs


def growth_ref(e, kind):
    """同比/环比参照区间：优先用官方表述的共识值，否则用规范值推算。"""
    if kind in e:
        return e[kind]["value"], e[kind]["half"], "stated"
    k2 = ("prior_y" if kind == "yoy" else "prior_q") + "_growth"
    if k2 in e:
        return e[k2]["value"], e[k2]["half"], "calc"
    return None

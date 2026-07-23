"""Rebuild emails.json as a hard, realistic phishing dataset.

    python -m tools.generate_emails > emails.json

Design rule: every malicious email has a benign twin from the same scenario that
shares its surface features — same domain style, same urgency, same attachment,
same mention of logins or money. Only the semantics differ. That kills the cheap
heuristics ("unknown domain", "says urgent", "mentions password") and leaves only
prompts that describe what actually makes an email an attack:

  - it wants a secret (password, PIN, 2FA code, account number) sent or typed
    into a page it links to, instead of sending you to a site you already trust
  - it routes around a process that exists to verify identity (payroll changes by
    email, gift cards for an executive, invoice bank details changed mid-thread)
  - the attachment does not match what the mail claims to be
  - it discourages the exact check that would expose it ("don't call", "keep this
    between us", "approve the prompt even if you didn't start it")

Benign mail here deliberately trips surface heuristics: real vendors on unfamiliar
domains, real deadlines, real security alerts, a CTF club shipping executables.
"""

import json
import random

rng = random.Random(20260724)

FIRST = ["지훈", "서연", "민준", "예린", "도현", "하은", "준우", "다연", "성민", "유진",
         "재현", "소율", "태윤", "지안", "현우", "채원", "건우", "수아", "동هyun", "나윤"]
LAST = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권"]


def person() -> str:
    return rng.choice(LAST) + rng.choice(FIRST).replace("동هyun", "동현")


def ref() -> str:
    return f"{rng.choice(['HD', 'SR', 'REQ', 'INC', 'OP'])}-{rng.randint(100000, 999999)}"


def money() -> str:
    return f"{rng.randint(12, 890) * 1000:,}"


def day(month: int) -> str:
    return f"{month:02d}월 {rng.randint(1, 28):02d}일"


def clock() -> str:
    return f"{rng.randint(9, 19):02d}:{rng.choice(['00', '10', '20', '30', '40', '50'])}"


# Benign mail links too — to places the reader already trusts. Without this, "contains
# a URL" separates the classes by itself and no real prompt skill is needed. The link
# has to match the sender, or the mismatch becomes its own giveaway.
LINKS = {
    "hancom": ["https://portal.hancom.com/notice/{n}", "https://portal.hancom.com/hr/payslip",
               "https://wiki.hancom.com/pages/{n}", "https://portal.hancom.com/security/mfa",
               "https://portal.hancom.com/card/{n}", "https://portal.hancom.com/survey/{n}"],
    "dimigo": ["https://www.dimigo.hs.kr/board/notice/{n}", "https://portal.dimigo.hs.kr/apply/{n}",
               "https://classroom.google.com/c/{n}"],
    "github.com": ["https://github.com/dimi-security/ctf-platform/pull/{n}"],
    "notion.so": ["https://notion.so/dimi-security/{n}"],
    "slack.com": ["https://dimi-security.slack.com/archives/C{n}"],
    "figma.com": ["https://figma.com/file/{n}"],
    "classroom.google.com": ["https://classroom.google.com/c/{n}"],
    "accounts.google.com": ["https://myaccount.google.com/security"],
    "atlassian.net": ["https://dimi-security.atlassian.net/browse/SEC-{n}"],
    "auto.hometax.go.kr": ["https://www.hometax.go.kr"],
    "notice.wooribank.com": ["https://spot.wooribank.com"],
    "svc.toss.im": ["https://toss.im/logout-guide"],
    "stealth-club.kr": ["https://gitlab.stealth-club.kr/ctf/review/-/issues/{n}"],
}


def good_link(key: str = "hancom") -> str:
    return rng.choice(LINKS.get(key, LINKS["hancom"])).format(n=rng.randint(100, 999999))


def phrase(*options: str) -> str:
    return rng.choice(options)


# Domains that are genuinely ours / genuinely well known.
INTERNAL = ["hancom.com", "dimigo.hs.kr"]
KNOWN_SAAS = ["github.com", "notion.so", "classroom.google.com", "accounts.google.com",
              "slack.com", "figma.com", "atlassian.net"]
# Real outside partners on domains nobody recognises. Benign mail uses these on
# purpose, so "unfamiliar domain" cannot be the rule.
ODD_BUT_REAL = ["mail.kyobobook.co.kr", "noreply.gabia.com", "billing.cafe24.com",
                "info.koreanair.com", "svc.toss.im", "notice.wooribank.com",
                "help.kakaoenterprise.com", "no-reply.jobkorea.co.kr",
                "mailer.incruit.com", "auto.hometax.go.kr", "cs.coupangbusiness.com",
                "ticket.interpark.com", "edm.yes24.com", "noreply.zoom.us"]
# Lookalikes. Used by *some* malicious mail — but only a minority, so the domain
# check alone leaves most attacks standing.
LOOKALIKE = ["hancom-hr.com", "dimigo-hs.kr", "g1thub.com", "not1on.so",
             "accounts-google.com.security-check.net", "hancom.com.mx",
             "slack-workspace.net", "classroom-google.kr"]

# Most real phishing arrives from a mailbox that already looks right — a compromised
# colleague, a spoofed header. Weighting toward the real domain stops "sender domain
# is not ours" from being the whole answer.
def spoofed(prefix: str) -> str:
    pool = INTERNAL if rng.random() < 0.62 else LOOKALIKE
    return f"{prefix}@{rng.choice(pool)}"


emails: list[dict] = []


def add(sender, subject, body, attachment, malicious, indicators, month=8):
    emails.append({
        "sender": sender,
        "subject": subject,
        "body": " ".join(body.split()),
        "date": f"2026-{month:02d}-{rng.randint(1, 28):02d} {clock()}",
        "attachment": attachment,
        "is_malicious": malicious,
        "indicators": indicators,
    })


# ---------------------------------------------------------------- scenarios
# Each block emits a benign and a malicious variant that look alike on the surface.

def scenario_password_expiry(n):
    for _ in range(n):
        d = rng.choice(INTERNAL)
        r = ref()
        add(f"it-helpdesk@{d}", f"사내 계정 비밀번호 만료 예정 안내 ({r})",
            f"""회원님의 사내 계정 비밀번호가 {day(8)}에 만료됩니다. 만료 전 사내 포털에 직접 접속하여
            [내 정보 > 비밀번호 변경]에서 갱신해 주세요. 사내 포털: {good_link()}
            헬프데스크는 어떤 경우에도 비밀번호를 묻지 않습니다.""",
            "", False, ["비밀번호 만료 안내", "사내 포털 링크 포함", "비밀번호를 묻지 않음"])
        # Twin: same helpdesk, same expiry story, but it hands you a page to type into.
        sender = spoofed("it-helpdesk")
        add(sender, f"[중요] 비밀번호 만료 {rng.randint(2, 24)}시간 전 — 즉시 갱신 필요 ({r})",
            f"""비밀번호 만료가 임박했습니다. 아래 페이지에서 현재 비밀번호와 새 비밀번호를 입력해 즉시 갱신해 주세요.
            기한 내 갱신하지 않으면 메일과 그룹웨어 접속이 차단됩니다. 갱신: https://sso-{rng.randint(10, 99)}.portal-reset.net/pw""",
            "", True, ["현재 비밀번호 입력 요구", "외부 도메인 입력 페이지", "차단 위협으로 압박"])


def scenario_payroll(n):
    for _ in range(n):
        r = ref()
        add(f"payroll@{rng.choice(INTERNAL)}", f"{day(8)} 급여명세서 발행 안내",
            f"""8월 급여명세서가 발행되었습니다. 명세서는 보안상 메일로 첨부하지 않으며,
            사내 인사시스템 {good_link()} 에 로그인하여 [급여 > 명세서 조회]에서 확인하실 수 있습니다.
            조회 기한은 {day(9)}까지이며 기한이 지나면 재발행 신청이 필요합니다. 문의는 인사팀 내선 {rng.randint(2000, 2999)}번입니다.""",
            "", False, ["급여 관련 메일", "사내 시스템 로그인 안내", "첨부 없음"])
        add(spoofed("payroll"), f"급여 수령 계좌 변경 접수 확인 요청 ({r})",
            f"""귀하의 급여 수령 계좌 변경 신청이 접수되었습니다. 본인이 신청하지 않았다면 아래 양식에
            사번과 기존 계좌번호를 입력하여 {day(8)}까지 취소해 주세요. 인사팀 유선 문의는 결산 기간이라
            응대가 어렵습니다. 취소 양식: https://hr-verify-{rng.randint(100, 999)}.info/cancel""",
            "", True, ["계좌번호 입력 요구", "유선 확인 차단", "불안감을 이용한 취소 유도"])


def scenario_exec_request(n):
    for _ in range(n):
        who, me = person(), person()
        add(f"ceo.office@{INTERNAL[0]}", f"{day(8)} 임원 워크숍 자료 취합 요청",
            f"""{day(8)} 임원 워크숍에 사용할 부서별 실적 자료를 취합하고 있습니다. 담당자는 {who} 책임이며,
            양식은 그룹웨어 공지사항 {good_link()} 에 올려 두었습니다. 기한은 {day(8)} 18시까지입니다.
            일정 조율이 필요하면 비서실 {who}에게 회신해 주세요.""",
            "", False, ["임원실 발신", "기한 명시", "업무 자료 요청"])
        add(f"ceo.office@{INTERNAL[0]}", rng.choice(["잠깐 시간 되나요", "지금 자리에 있나요", "급한 건 하나만"]),
            f"""지금 외부 미팅 중이라 통화가 어렵습니다. 거래처 감사 선물로 모바일 상품권
            {rng.randint(3, 8)}장을 먼저 구매해 주세요. 구매 후 핀 번호 사진만 이 메일로 보내주면
            오후에 법인카드로 정산하겠습니다. 아직 공식 발표 전이라 팀에는 공유하지 말아 주세요.""",
            "", True, ["임원 사칭 상품권 요구", "핀 번호 전송 요구", "통화 회피와 비밀 유지 요구"])


def scenario_invoice(n):
    for _ in range(n):
        vendor, vhost = rng.choice([("바이트웍스", "byteworks.co.kr"), ("클라우드웍스", "cloudworks.co.kr"),
                                    ("데이터라인", "dataline.kr"), ("한빛솔루션", "hanbit-sol.co.kr"),
                                    ("코드메이커", "codemaker.io")])
        r = ref()
        add(f"billing@{vhost}", f"[{vendor}] {day(8)} 정기 이용료 청구서 발행 ({r})",
            f"""{vendor} 8월 이용료 {money()}원 청구서가 발행되었습니다. 결제 계좌는 계약서에 명시된
            기존 계좌와 동일합니다. 세금계산서는 홈택스 https://www.hometax.go.kr 에서 자동 발행되며, 청구 내역은 고객센터
            {rng.randint(1500, 1599)}-{rng.randint(1000, 9999)}로 문의하실 수 있습니다.""",
            f"{vendor}_청구서_08월.pdf", False, ["외부 결제 관련 메일", "낯선 발신 도메인", "첨부 청구서"])
        add(f"billing@{vhost}", f"Re: [{vendor}] {day(8)} 정기 이용료 청구서 ({r}) — 입금 계좌 변경",
            f"""안내드린 청구 건 관련하여, 당사 주거래 은행 변경으로 입금 계좌가 바뀌었습니다.
            기존 계좌로 입금 시 처리가 지연되니 아래 신규 계좌로 송금 부탁드립니다.
            신규 계좌: {rng.choice(['우리', '국민', '하나'])}은행 {rng.randint(100, 999)}-{rng.randint(100000, 999999)}-{rng.randint(10, 99)}
            (예금주: {vendor} 대표 {person()}). 계좌 변경 확인 전화는 담당자 외근으로 어렵습니다.""",
            "", True, ["기존 스레드에 끼어든 계좌 변경", "유선 확인 차단", "송금처 변경 유도"])


def scenario_security_alert(n):
    for _ in range(n):
        svc, host = rng.choice([("Google", "accounts.google.com"), ("GitHub", "github.com"),
                                ("Slack", "slack.com"), ("Notion", "notion.so")])
        add(f"no-reply@{host}", f"보안 알림: 새로운 기기에서 {svc} 계정에 로그인",
            f"""{day(8)} {clock()}에 {rng.choice(['Windows', 'Linux', 'macOS', 'Android'])} 기기에서
            로그인이 감지되었습니다. 본인이라면 조치가 필요 없습니다. 본인이 아니라면 이 메일의 링크가 아니라
            {svc} 공식 사이트 {good_link(host)} 를 주소창에 직접 입력해 접속한 뒤 보안 설정에서 세션을 종료하세요.""",
            "", False, ["보안 경고 문구", "새 기기 로그인 알림", "링크 대신 직접 접속 권고"])
        add(f"security-alert@{rng.choice([host, host, rng.choice(LOOKALIKE)])}", f"[경고] {svc} 계정 비정상 접근 — {rng.randint(15, 60)}분 내 확인 필요",
            f"""해외 IP에서 {svc} 계정 접근이 감지되어 일부 기능이 제한되었습니다. 아래 확인 페이지에서
            로그인하여 본인 인증을 완료하지 않으면 계정이 영구 잠금 처리됩니다.
            확인: https://{svc.lower().split()[0]}-verify-{rng.randint(10, 99)}.account-check.co/auth""",
            "", True, ["외부 인증 페이지로 로그인 유도", "영구 잠금 위협", "짧은 제한 시간"])


def scenario_mfa(n):
    for _ in range(n):
        add(f"security@{INTERNAL[0]}", f"다단계 인증(MFA) {rng.choice(['등록', '재등록', '기기 변경'])} 안내 ({day(rng.choice([8,9]))})",
            f"""사내 시스템 MFA 등록이 {day(9)}부터 의무화됩니다. 등록은 사내 포털 {good_link()} 의 [보안 설정] 메뉴에서 직접 진행하시면 됩니다. 보안팀은 인증 앱에 뜨는 숫자나 코드를 절대 묻지 않으며,
            본인이 시작하지 않은 승인 요청은 반드시 거부해 주세요.""",
            "", False, ["MFA 관련 안내", "보안팀 발신", "코드 요구 없음"])
        add(f"security@{INTERNAL[0]}", f"{rng.choice(['VPN 인증서 갱신', '사내망 접속 인증서 재발급', '원격근무 인증 갱신'])} — 모바일 승인 필요 ({ref()})",
            f"""VPN 인증서 갱신 작업 중 계정별 모바일 승인이 필요합니다. 잠시 후 인증 앱에 표시되는
            숫자 {rng.randint(10, 89)}를 선택해 주세요. 본인이 시작하지 않은 요청으로 보이더라도
            갱신 절차상 정상이니 그대로 승인하시면 됩니다.""",
            "", True, ["요청하지 않은 MFA 승인 유도", "보안 경고를 무시하도록 지시", "내부 계정 탈취 정황"])


def scenario_club_files(n):
    for _ in range(n):
        add(f"ctf@stealth-club.kr", f"{day(8)} 문제 검수용 파일 전달 — 배치 {rng.randint(100, 499)}",
            f"""이번 주 검수 대상 리버싱/포렌식 문제 파일을 전달합니다. 압축 안에 실행 파일과 패킷 캡처가
            포함되어 있으니 반드시 동아리 분석용 가상머신에서만 실행해 주세요. 비밀번호는 회의 때 공유한
            그 값입니다. 검수 결과는 {good_link("stealth-club.kr")} 이슈에 남겨 주세요.""",
            f"ctf_review_{rng.randint(100, 499)}.zip", False,
            ["압축 첨부파일", "실행 파일 포함", "분석 환경에서만 실행 안내"])
        add(f"ctf-support@{rng.choice(['stealth-club.kr', 'stealth-club.kr', 'ctf-stealth.club'])}",
            f"{day(8)} 대회 참가자 계정 확인 요청",
            f"""대회 서버 이관으로 참가자 계정 재확인이 필요합니다. 첨부된 문서를 열어 안내에 따라
            동아리 계정과 비밀번호를 입력해 주세요. 미확인 계정은 {day(8)}에 삭제됩니다.""",
            f"참가자확인_{rng.randint(100, 999)}.docm", True,
            ["매크로 문서 첨부", "계정과 비밀번호 입력 요구", "삭제 위협"])


def scenario_delivery(n):
    for _ in range(n):
        t = f"{rng.randint(100000000000, 999999999999)}"
        add(f"no-reply@{rng.choice(ODD_BUT_REAL)}", f"[배송] 주문하신 상품이 발송되었습니다 ({t[:6]})",
            f"""주문번호 {ref()} 상품이 {day(8)} 발송되었습니다. 운송장번호는 {t}이며,
            배송 조회는 택배사 앱이나 홈페이지에서 운송장번호로 직접 조회해 주세요.
            주문 내역은 {good_link()} 에서 확인하실 수 있습니다.""",
            "", False, ["배송 알림", "낯선 발신 도메인", "운송장번호 안내"])
        add(f"delivery@{rng.choice(['post-redelivery.info', 'parcel-check.net'] + ODD_BUT_REAL)}",
            f"[재배송] {rng.choice(['주소 불명', '수령인 부재', '우편번호 오류'])}으로 배송이 보류되었습니다 ({ref()})",
            f"""주소 정보 불일치로 배송이 보류 중입니다. {day(8)}까지 아래 페이지에서 수령인 정보와
            결제 카드 정보를 확인하지 않으면 반송 처리됩니다. 재배송 신청:
            https://redelivery-{rng.randint(100, 999)}.parcel-check.net/form""",
            "", True, ["카드 정보 입력 요구", "반송 위협", "외부 정보 입력 페이지"])


def scenario_school_notice(n):
    topics = ["수행평가 제출 형식", "동아리 발표회 일정", "기숙사 점호 시간 변경", "체육대회 종목 신청",
              "진로 특강 신청", "도서관 좌석 배정", "급식 메뉴 변경", "정보올림피아드 교내 예선",
              "방과후 수업 수강 신청", "학생회 예산 심의"]
    for _ in range(n):
        t = rng.choice(topics)
        add(f"{rng.choice(['teacher.kim', 'teacher.lee', 'council', 'notice', 'library'])}@{INTERNAL[1]}",
            f"{t} 안내 ({day(rng.choice([8,9,10]))}, {ref()})",
            f"""{t} 관련 안내드립니다. 자세한 내용은 학교 포털 공지사항에 게시되어 있으며,
            신청이 필요한 경우 학교 포털 {good_link("dimigo")} 에 학생 계정으로 로그인한 뒤 진행해 주세요.
            신청 마감은 {day(9)}이며 마감 후에는 접수가 불가합니다. 문의는 담당 교사에게 직접 연락 바랍니다.""",
            "", False, ["학교 공지", "포털 로그인 안내", "교내 절차 안내"])


def scenario_saas_normal(n):
    acts = [("GitHub", "리뷰 요청", "pull request #{} 리뷰를 요청했습니다. 변경 사항은 저장소의 Pull requests 탭에서 확인하실 수 있습니다."),
            ("Notion", "페이지 공유", "{} 페이지를 공유했습니다. 워크스페이스에 로그인하면 좌측 공유됨 목록에서 볼 수 있습니다."),
            ("Slack", "채널 초대", "#{} 채널에 초대되었습니다. Slack 앱을 열면 채널 목록에 표시됩니다."),
            ("Figma", "댓글 알림", "{} 파일에 새 댓글이 달렸습니다. Figma 앱에서 확인해 주세요.")]
    for _ in range(n):
        svc, kind, tmpl = rng.choice(acts)
        host = {"GitHub": "github.com", "Notion": "notion.so", "Slack": "slack.com", "Figma": "figma.com"}[svc]
        arg = str(rng.randint(10, 99)) if svc == "GitHub" else rng.choice(["설계-초안", "보안-스터디", "UI-리뉴얼", "인프라-점검"])
        add(f"notifications@{host}", f"[{svc}] {kind}: {arg} #{rng.randint(100, 999)}",
            f"""{person()}님이 {tmpl.format(arg)} 바로가기: {good_link(host)} 알림 설정은 계정 설정에서 변경할 수 있습니다.""",
            "", False, ["협업 도구 알림", "정상 서비스 도메인"])


def scenario_saas_phish(n):
    for _ in range(n):
        svc = rng.choice(["GitHub", "Notion", "Slack", "Figma"])
        add(f"notifications@{rng.choice(KNOWN_SAAS + KNOWN_SAAS + LOOKALIKE)}",
            f"[{svc}] 공유 문서 열람 권한 확인 필요",
            f"""{person()}님이 보안 문서를 공유했습니다. 문서 열람을 위해 아래 페이지에서 회사 계정으로
            로그인하여 권한을 확인해 주세요. {rng.randint(24, 72)}시간 내 확인하지 않으면 공유가 만료됩니다.
            열람: https://{svc.lower()}-share-{rng.randint(10, 99)}.doc-access.net/view""",
            "", True, ["외부 페이지에서 회사 계정 로그인 요구", "만료 압박", "협업 알림 사칭"])


def scenario_job(n):
    for _ in range(n):
        add(f"recruit@{rng.choice(ODD_BUT_REAL)}", f"[채용] {rng.choice(['백엔드', '보안', '데이터'])} 직무 지원 접수 확인",
            f"""지원해 주셔서 감사합니다. 제출하신 서류는 정상 접수되었으며 서류 결과는 {day(9)}에 지원 사이트 마이페이지 {good_link()} 에서 확인하실 수 있습니다. 별도의 개인정보나 계좌 정보를
            메일로 요청하는 일은 없습니다.""",
            "", False, ["채용 관련 메일", "낯선 발신 도메인", "마이페이지 확인 안내"])
        add(f"hr@{rng.choice(ODD_BUT_REAL + LOOKALIKE)}", f"[채용] {rng.choice(['최종 합격', '입사 확정', '채용 확정'])} 안내 및 입사 서류 제출 ({day(rng.choice([8,9]))})",
            f"""최종 합격을 축하드립니다. 입사 처리를 위해 첨부 양식에 주민등록번호, 급여 이체 계좌,
            공인인증서 비밀번호를 기입하여 {day(9)}까지 회신해 주세요. 회신이 늦어지면 합격이 취소될 수 있습니다.""",
            f"입사서류_{rng.randint(1000, 9999)}.docm", True,
            ["민감 개인정보 요구", "인증서 비밀번호 요구", "매크로 문서 첨부"])


def scenario_finance_normal(n):
    for _ in range(n):
        add(f"finance@{INTERNAL[0]}", f"법인카드 {day(rng.choice([8,9]))} 사용 내역 확인 요청 ({ref()})",
            f"""{day(8)} 해외 소프트웨어 구독료 {money()}원이 법인카드로 승인되었습니다. 업무상 결제가 맞는지
            법인카드 시스템 {good_link()} 에서 확인해 주세요. {day(9)}까지 확인되지 않으면 회계 처리가 보류됩니다. 본인 사용이 아닌 경우 카드번호를 메일로 회신하지 마시고 재무팀 내선 {rng.randint(3000, 3999)}번으로 연락 주세요.""",
            "", False, ["해외 결제 알림", "금액 명시", "카드번호 회신 금지 안내"])


def scenario_tax_normal(n):
    for _ in range(n):
        host, brand = rng.choice([("auto.hometax.go.kr", "홈택스"), ("notice.wooribank.com", "우리은행"), ("svc.toss.im", "토스")])
        add(f"noreply@{host}",
            f"[{brand}] {day(rng.choice([8,9]))} 이용 내역 안내 ({ref()})",
            f"""{day(8)} 기준 이용 내역을 안내드립니다. 상세 내역은 {brand} 공식 홈페이지 {good_link(host)} 에 직접 접속하여 로그인 후 확인해 주세요. 당사는 메일이나 문자로 비밀번호, 보안카드 번호, OTP를 요구하지 않습니다.""",
            "", False, ["금융 기관 발신", "직접 접속 안내", "정보 요구 없음"])


def scenario_survey(n):
    for _ in range(n):
        add(f"survey@{rng.choice(INTERNAL)}", f"{day(9)} {rng.choice(['조직문화', '학교생활', '복지제도', '교육과정'])} 만족도 설문",
            f"""익명 설문입니다. 참여 기간은 {day(9)}까지이며, 사내 포털 설문 메뉴 {good_link()} 에서 계정 로그인 후 1회 참여할 수 있습니다. 설문 결과는 통계 목적으로만 사용되며 개별 응답은 식별되지 않습니다.""",
            "", False, ["설문 참여 요청", "포털 로그인 안내"])
        add(f"survey-reward@{rng.choice(ODD_BUT_REAL + LOOKALIKE)}",
            f"[경품] 만족도 설문 참여자 {money()}원 상품권 지급 안내",
            f"""설문 참여 감사 경품에 당첨되셨습니다. 상품권 수령을 위해 아래 페이지에서 사내 계정으로
            로그인한 뒤 본인 확인을 완료해 주세요. {day(9)}까지 미확인 시 자동 소멸됩니다.
            수령: https://reward-{rng.randint(100, 999)}.gift-claim.net""",
            "", True, ["경품 미끼", "외부 페이지 사내 계정 로그인 요구", "소멸 기한 압박"])


def scenario_thread_hijack(n):
    subjects = ["프로젝트 일정 재조정 건", "API 명세 검토 요청", "보안 점검 결과 공유",
                "예산 집행 계획 확인", "외부 감사 대응 자료"]
    for _ in range(n):
        s = rng.choice(subjects)
        add(f"{rng.choice(['dev', 'pm', 'audit'])}@{INTERNAL[0]}", f"Re: Re: {s} ({day(rng.choice([8,9]))})",
            f"""앞서 논의한 내용 정리해서 공유드립니다. 수정 사항은 사내 위키 {good_link()} 에 반영해 두었고,
            추가 의견은 위키 댓글로 남겨 주세요. 다음 회의는 {day(8)} {clock()}입니다.""",
            "", False, ["기존 스레드 회신", "내부 도메인", "위키 안내"])
        add(f"{rng.choice(['dev', 'pm', 'audit'])}@{INTERNAL[0]}", f"Re: Re: {s} ({day(rng.choice([8,9]))})",
            f"""공유드린 문서가 열람 권한 문제로 안 열린다는 분들이 있어 외부 뷰어로 다시 올렸습니다.
            아래 링크에서 회사 메일 계정으로 로그인하시면 바로 보실 수 있습니다.
            https://docs-view-{rng.randint(100, 999)}.file-share.co/open?id={rng.randint(10000, 99999)}""",
            "", True, ["탈취된 내부 계정 정황", "외부 뷰어에서 회사 계정 로그인 요구", "기존 대화 악용"])


def scenario_it_maintenance(n):
    for _ in range(n):
        add(f"infra@{INTERNAL[0]}", f"[점검] {day(8)} {clock()} 그룹웨어 정기 점검 안내",
            f"""{day(8)} {clock()}부터 약 {rng.randint(2, 5)}시간 동안 그룹웨어 정기 점검이 진행됩니다.
            점검 중에는 메일 발송이 지연될 수 있습니다. 별도의 재로그인이나 인증 절차는 필요하지 않습니다.
            문의는 인프라팀 내선 {rng.randint(4000, 4999)}번입니다.""",
            "", False, ["시스템 점검 공지", "내부 발신"])
        add(spoofed("infra"), f"[점검] {rng.choice(['메일 서버 이관', '그룹웨어 인증 서버 교체', 'SSO 전환 작업', '메일함 용량 정책 변경'])} — 계정 재인증 필요 ({ref()})",
            f"""메일 서버 이관 작업으로 전 직원 계정 재인증이 필요합니다. {day(8)}까지 아래 페이지에서
            아이디와 비밀번호로 재인증하지 않으면 메일 수신이 중단되며 미수신 메일은 복구되지 않습니다.
            재인증: https://mail-migrate-{rng.randint(10, 99)}.relay-auth.net""",
            "", True, ["아이디·비밀번호 재입력 요구", "외부 인증 페이지", "메일 손실 위협"])


def scenario_misc_benign(n):
    kinds = [
        ("교육", "{} 정보보안 교육 이수 안내", "분기 정보보안 교육이 사내 교육 포털에 등록되었습니다. 이수 기한은 {}이며 소요 시간은 약 {}분입니다. 교육 포털에 직접 접속해 수강해 주세요."),
        ("복지", "{} 건강검진 예약 안내", "올해 건강검진 예약이 시작되었습니다. 검진 기관과 일정은 복지 포털에서 직접 선택하실 수 있습니다. 예약 마감은 {}입니다. 문의는 총무팀으로 부탁드립니다."),
        ("행사", "{} 사내 세미나 참가 신청", "외부 연사를 초청한 기술 세미나를 진행합니다. 신청은 그룹웨어 행사 게시판에서 받으며 정원은 {}명입니다. 마감은 {}입니다."),
        ("공지", "{} 사무실 이전 안내", "본사 사무실이 {}층으로 이전합니다. 이전일은 {}이며 당일 네트워크가 일시 중단될 수 있습니다. 좌석 배치도는 그룹웨어에 게시했습니다."),
        ("회의", "{} 주간 회의록 공유", "이번 주 회의록을 공유합니다. 상세 내용은 사내 위키에 정리해 두었으며 수정 의견은 {}까지 댓글로 남겨 주세요."),
    ]
    for _ in range(n):
        tag, subj, body = rng.choice(kinds)
        d1, d2 = day(8), day(9)
        add(f"{rng.choice(['hr', 'admin', 'infra', 'edu', 'welfare'])}@{rng.choice(INTERNAL)}",
            f"[{tag}] " + subj.format(d1) + f" ({ref()})",
            body.format(d2, rng.randint(10, 90)) if body.count("{}") == 2 else body.format(d2, rng.randint(10, 90), d1),
            "", False, [])


SCENARIOS = [
    (scenario_password_expiry, 10), (scenario_payroll, 10), (scenario_exec_request, 9),
    (scenario_invoice, 10), (scenario_security_alert, 11), (scenario_mfa, 8),
    (scenario_club_files, 8), (scenario_delivery, 9), (scenario_job, 9),
    (scenario_survey, 8), (scenario_thread_hijack, 10), (scenario_it_maintenance, 10),
    (scenario_saas_phish, 13),
    # benign-only filler so the malicious ratio stays realistic
    (scenario_school_notice, 60), (scenario_saas_normal, 55), (scenario_finance_normal, 40),
    (scenario_tax_normal, 38), (scenario_misc_benign, 70),
]

for fn, count in SCENARIOS:
    fn(count)

rng.shuffle(emails)
for i, e in enumerate(emails, start=1):
    e["id"] = i
    e["read"] = False
    e["deleted"] = False

ordered = [{k: e[k] for k in ("id", "sender", "subject", "body", "date", "attachment",
                              "is_malicious", "indicators", "read", "deleted")} for e in emails]
print(json.dumps(ordered, ensure_ascii=False, indent=2))

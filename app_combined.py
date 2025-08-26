# app_combined.py
"""
한 서버에서 team_ranking_back_alt(팀순위)와 hour_back_alt(평균 경기시간)를 함께 서비스하는 조립용 엔트리포인트.

- 기존 team_ranking_back_alt.py 안의 Flask 앱(app)을 그대로 재사용
- hour_back_alt의 블루프린트(/hour, /hour/ping)를 등록
- "/" 에서 templates/combined.html 렌더 (좌: /team-ranking, 우: /hour)
"""

from flask import render_template
try:
    # 기존 팀순위 앱의 Flask 인스턴스를 재사용
    from team_ranking_back_alt import app as app
except Exception as e:
    # 혹시 모를 케이스 대비: team_ranking_back_alt 가 없다면 새 앱 생성
    from flask import Flask
    app = Flask(__name__)

# 평균 경기시간 블루프린트 등록
from hour_back_alt import hour_bp
# 이미 등록되어 있더라도 중복 에러가 나지 않도록 방어
if "hour_alt" not in app.blueprints:
    app.register_blueprint(hour_bp)  # /hour, /hour/ping

# 대시보드(통합) 홈 라우트
@app.route("/")
def combined_dashboard():
    # templates/combined.html 을 렌더링 (이미 제공한 파일)
    return render_template("combined.html")


# 선택: 팀순위 경로가 /team-ranking 가 아닐 수 있으므로 호환용 리다이렉트(있으면 주석 해제)
# from flask import redirect
# @app.route("/ranking")
# def _compat_ranking():
#     return redirect("/team-ranking", code=302)


if __name__ == "__main__":
    # 로컬 테스트: python app_combined.py
    app.run(host="0.0.0.0", port=5002, debug=True)

from flask import Flask, render_template
from shorts import fetch_kbo_shorts

app = Flask(__name__)

@app.route("/")
def show_shorts():
    shorts = fetch_kbo_shorts()
    return render_template("shorts.html", shorts=shorts)

if __name__ == "__main__":
    app.run(debug=True)


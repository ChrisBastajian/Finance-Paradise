from flask import Flask, render_template, request

app = Flask(__name__)

data = [
    {"title": "Apple", "content": "A fruit"},
    {"title": "Python", "content": "Programming language"},
    {"title": "Dog", "content": "An animal"}
]

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/search")
def search():
    query = request.args.get("q", "").lower()

    results = [item for item in data if query in item["title"].lower()]

    return render_template("results.html", query=query, results=results)

if __name__ == "__main__":
    app.run(debug=True)
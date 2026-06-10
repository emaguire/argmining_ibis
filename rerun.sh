
docker rm -f argmine-ibis
docker build -t argmine-ibis .
docker run --name argmine-ibis -p 8060:5000 -d argmine-ibis
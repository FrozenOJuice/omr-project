
#
# Runs the server in Docker.
#

docker kill omr
docker container rm omr

docker build --tag omr_server .
docker run --rm -p 3000:3000 --name omr --detach omr_server
docker exec -t omr sh -c "go test ./..."

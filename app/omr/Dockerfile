# The official GoCV image
FROM ghcr.io/hybridgroup/opencv:4.13.0

ENV GOPATH=/go

#
# Build the app
#

COPY . /app

WORKDIR /app
RUN go build -o /build/omr .

#
# Run the app
#

ENTRYPOINT ["/build/omr"]
CMD ["serve"]

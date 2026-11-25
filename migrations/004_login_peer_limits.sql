CREATE TABLE login_peer_limits (
    peer TEXT NOT NULL,
    window INTEGER NOT NULL,
    attempts INTEGER NOT NULL CHECK(attempts BETWEEN 1 AND 30),
    PRIMARY KEY (peer, window)
);
CREATE INDEX login_peer_windows ON login_peer_limits(window);

CREATE TABLE user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL
  email TEXT
  registered DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE program (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (owner_id) REFERENCES user (id)
);


CREATE TABLE exercise (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  with_weight BOOLEAN NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES user (id)
);


CREATE TABLE training (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_finished TIMESTAMP,
  FOREIGN KEY (owner_id) REFERENCES user (id)
);


CREATE TABLE set (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL,
  training_id INTEGER NOT NULL,
  exercise_id INTEGER NOT NULL,
  repetitions INTEGER NOT NULL,
  weight INTEGER NOT NULL,
  linked_with
  FOREIGN KEY (owner_id) REFERENCES user (id)
  FOREIGN KEY (owner_id) REFERENCES user (id)
);

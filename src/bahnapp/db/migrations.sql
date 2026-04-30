CREATE TABLE IF NOT EXISTS stations (
  eva_no       BIGINT PRIMARY KEY,
  name         VARCHAR(255) NOT NULL,
  ds100        VARCHAR(16),
  updated_at   DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS tracking_jobs (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  origin_eva    BIGINT NOT NULL,
  dest_eva      BIGINT NOT NULL,
  start_date    DATE NOT NULL,
  end_date      DATE NOT NULL,
  train_filter  VARCHAR(32) NOT NULL DEFAULT 'ICE',
  max_umstiege  TINYINT NOT NULL DEFAULT 2,
  status        ENUM('active','paused','completed') NOT NULL DEFAULT 'active',
  created_by    VARCHAR(255) NOT NULL,
  created_at    DATETIME NOT NULL,
  CONSTRAINT fk_origin FOREIGN KEY (origin_eva) REFERENCES stations(eva_no),
  CONSTRAINT fk_dest   FOREIGN KEY (dest_eva)   REFERENCES stations(eva_no)
);

CREATE TABLE IF NOT EXISTS reisen (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_id            BIGINT NOT NULL,
  travel_date       DATE NOT NULL,
  refresh_token     VARCHAR(512) NULL,
  planned_departure DATETIME NOT NULL,
  planned_arrival   DATETIME NOT NULL,
  anzahl_etappen    TINYINT NOT NULL,
  outage_state      ENUM('pending','on_time','delayed','outage') NOT NULL DEFAULT 'pending',
  outage_reason     VARCHAR(64) NULL,
  total_delay_min   INT NULL,
  finalized_at      DATETIME NULL,
  last_updated      DATETIME NOT NULL,
  UNIQUE KEY uniq_job_reise (job_id, travel_date, planned_departure, anzahl_etappen),
  CONSTRAINT fk_reise_job FOREIGN KEY (job_id) REFERENCES tracking_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reise_etappen (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  reise_id            BIGINT NOT NULL,
  etappe_index        TINYINT NOT NULL,
  train_number        VARCHAR(32) NOT NULL,
  hafas_trip_id       VARCHAR(255) NULL,
  origin_eva          BIGINT NOT NULL,
  dest_eva            BIGINT NOT NULL,
  origin_planned      DATETIME NOT NULL,
  origin_actual       DATETIME NULL,
  origin_status       ENUM('scheduled','on_time','delayed','stop_cancelled','cancelled') NOT NULL DEFAULT 'scheduled',
  dest_planned        DATETIME NOT NULL,
  dest_actual         DATETIME NULL,
  dest_status         ENUM('scheduled','on_time','delayed','stop_cancelled','cancelled') NOT NULL DEFAULT 'scheduled',
  delay_minutes       INT NULL,
  min_umsteige_min    SMALLINT NULL,
  raw_messages        JSON NULL,
  last_updated        DATETIME NOT NULL,
  UNIQUE KEY uniq_reise_etappe (reise_id, etappe_index),
  CONSTRAINT fk_etappe_reise FOREIGN KEY (reise_id) REFERENCES reisen(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS poll_tasks (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  eva_no          BIGINT NOT NULL,
  scheduled_at    DATETIME NOT NULL,
  reason          ENUM('pre_dep_60','pre_dep_5','post_dep_5','pre_arr_5','post_arr_5','post_arr_30') NOT NULL,
  status          ENUM('pending','done','failed') NOT NULL DEFAULT 'pending',
  attempted_at    DATETIME NULL,
  attempts        TINYINT NOT NULL DEFAULT 0,
  UNIQUE KEY uniq_eva_bucket_reason (eva_no, scheduled_at, reason),
  KEY idx_status_scheduled (status, scheduled_at)
);

CREATE TABLE IF NOT EXISTS poll_task_etappen (
  poll_task_id  BIGINT NOT NULL,
  etappe_id     BIGINT NOT NULL,
  PRIMARY KEY (poll_task_id, etappe_id),
  CONSTRAINT fk_pte_task   FOREIGN KEY (poll_task_id) REFERENCES poll_tasks(id) ON DELETE CASCADE,
  CONSTRAINT fk_pte_etappe FOREIGN KEY (etappe_id)    REFERENCES reise_etappen(id) ON DELETE CASCADE
);

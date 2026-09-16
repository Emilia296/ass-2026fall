-- Generated schema from app/models.py. PostgreSQL 16+.

CREATE TABLE admin_user (
	id BIGSERIAL NOT NULL,
	username VARCHAR(255) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	real_name VARCHAR(255) NOT NULL,
	phone VARCHAR(255),
	status VARCHAR(255) NOT NULL,
	last_login_at TIMESTAMP WITH TIME ZONE,
	token_version BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (username)
)

;

CREATE TABLE charging_station (
	id BIGSERIAL NOT NULL,
	station_name VARCHAR(255) NOT NULL,
	city VARCHAR(255) NOT NULL,
	address VARCHAR(255) NOT NULL,
	longitude NUMERIC(18, 6) NOT NULL,
	latitude NUMERIC(18, 6) NOT NULL,
	business_start VARCHAR(255) NOT NULL,
	business_end VARCHAR(255) NOT NULL,
	contact_phone VARCHAR(255),
	parking_note TEXT,
	status VARCHAR(255) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)

;

CREATE TABLE coupon_template (
	id BIGSERIAL NOT NULL,
	coupon_name VARCHAR(255) NOT NULL,
	coupon_type VARCHAR(255) NOT NULL,
	min_amount NUMERIC(18, 6) NOT NULL,
	discount_amount NUMERIC(18, 6),
	discount_rate NUMERIC(18, 6),
	max_discount NUMERIC(18, 6),
	total_quantity BIGINT NOT NULL,
	per_user_limit BIGINT NOT NULL,
	valid_type VARCHAR(255) NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE,
	valid_to TIMESTAMP WITH TIME ZONE,
	valid_days BIGINT NOT NULL,
	points_cost BIGINT NOT NULL,
	status VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CHECK (total_quantity >= 0),
	CHECK (per_user_limit > 0),
	CHECK (points_cost >= 0)
)

;

CREATE TABLE login_log (
	id BIGSERIAL NOT NULL,
	account_type VARCHAR(255) NOT NULL,
	account_id BIGINT,
	phone_or_username VARCHAR(255) NOT NULL,
	login_method VARCHAR(255) NOT NULL,
	ip_address VARCHAR(255),
	device_info TEXT,
	result VARCHAR(255) NOT NULL,
	fail_reason TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)

;

CREATE TABLE sys_permission (
	id BIGSERIAL NOT NULL,
	permission_code VARCHAR(255) NOT NULL,
	permission_name VARCHAR(255) NOT NULL,
	permission_type VARCHAR(255) NOT NULL,
	parent_id BIGINT,
	route VARCHAR(255),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (permission_code)
)

;

CREATE TABLE sys_role (
	id BIGSERIAL NOT NULL,
	role_code VARCHAR(255) NOT NULL,
	role_name VARCHAR(255) NOT NULL,
	status VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (role_code)
)

;

CREATE TABLE system_config (
	id BIGSERIAL NOT NULL,
	config_key VARCHAR(255) NOT NULL,
	config_value VARCHAR(255) NOT NULL,
	description TEXT,
	updated_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (config_key)
)

;

CREATE TABLE "user" (
	id BIGSERIAL NOT NULL,
	phone VARCHAR(255) NOT NULL,
	password_hash VARCHAR(255),
	nickname VARCHAR(255) NOT NULL,
	avatar VARCHAR(255),
	points_balance BIGINT NOT NULL,
	credit_score BIGINT NOT NULL,
	status VARCHAR(255) NOT NULL,
	failed_login_count BIGINT NOT NULL,
	lock_until TIMESTAMP WITH TIME ZONE,
	manual_locked BOOLEAN NOT NULL,
	lock_reason TEXT,
	token_version BIGINT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (phone),
	CHECK (points_balance >= 0),
	CHECK (credit_score >= 0)
)

;

CREATE TABLE admin_user_role (
	id BIGSERIAL NOT NULL,
	admin_user_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (admin_user_id, role_id),
	FOREIGN KEY(admin_user_id) REFERENCES admin_user (id),
	FOREIGN KEY(role_id) REFERENCES sys_role (id)
)

;

CREATE TABLE charging_pile (
	id BIGSERIAL NOT NULL,
	station_id BIGINT NOT NULL,
	pile_no VARCHAR(255) NOT NULL,
	pile_type VARCHAR(255) NOT NULL,
	power_kw NUMERIC(18, 6) NOT NULL,
	qr_code VARCHAR(255) NOT NULL,
	status VARCHAR(255) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (pile_no),
	UNIQUE (qr_code),
	CHECK (pile_type IN ('FAST','SLOW')),
	CHECK (power_kw > 0),
	FOREIGN KEY(station_id) REFERENCES charging_station (id)
)

;

CREATE TABLE coupon_event_rule (
	id BIGSERIAL NOT NULL,
	event_type VARCHAR(255) NOT NULL,
	coupon_template_id BIGINT NOT NULL,
	min_consume_amount NUMERIC(18, 6) NOT NULL,
	probability NUMERIC(18, 6) NOT NULL,
	daily_limit BIGINT NOT NULL,
	status VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CHECK (probability BETWEEN 0 AND 1),
	CHECK (daily_limit > 0),
	FOREIGN KEY(coupon_template_id) REFERENCES coupon_template (id)
)

;

CREATE TABLE credit_record (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	change_type VARCHAR(255) NOT NULL,
	change_score BIGINT NOT NULL,
	score_before BIGINT NOT NULL,
	score_after BIGINT NOT NULL,
	biz_type VARCHAR(255) NOT NULL,
	biz_id BIGINT NOT NULL,
	remark TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES "user" (id)
)

;

CREATE TABLE occupancy_fee_rule (
	id BIGSERIAL NOT NULL,
	station_id BIGINT,
	free_minutes BIGINT NOT NULL,
	max_amount NUMERIC(18, 6),
	status VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id)
)

;

CREATE TABLE operation_log (
	id BIGSERIAL NOT NULL,
	admin_id BIGINT NOT NULL,
	role_name VARCHAR(255) NOT NULL,
	module VARCHAR(255) NOT NULL,
	operation_type VARCHAR(255) NOT NULL,
	target_type VARCHAR(255) NOT NULL,
	target_id BIGINT,
	before_data JSON,
	after_data JSON,
	reason TEXT,
	result VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(admin_id) REFERENCES admin_user (id)
)

;

CREATE TABLE points_record (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	change_type VARCHAR(255) NOT NULL,
	change_points BIGINT NOT NULL,
	balance_before BIGINT NOT NULL,
	balance_after BIGINT NOT NULL,
	biz_type VARCHAR(255) NOT NULL,
	biz_id BIGINT NOT NULL,
	remark TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES "user" (id)
)

;

CREATE TABLE role_permission (
	id BIGSERIAL NOT NULL,
	role_id BIGINT NOT NULL,
	permission_id BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (role_id, permission_id),
	FOREIGN KEY(role_id) REFERENCES sys_role (id),
	FOREIGN KEY(permission_id) REFERENCES sys_permission (id)
)

;

CREATE TABLE station_availability_watch (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	station_id BIGINT NOT NULL,
	pile_type VARCHAR(255) NOT NULL,
	status VARCHAR(255) NOT NULL,
	last_notified_at TIMESTAMP WITH TIME ZONE,
	cancelled_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (user_id, station_id),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id)
)

;

CREATE TABLE station_favorite (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	station_id BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (user_id, station_id),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id)
)

;

CREATE TABLE user_coupon (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	template_id BIGINT NOT NULL,
	coupon_code VARCHAR(255) NOT NULL,
	source_type VARCHAR(255) NOT NULL,
	status VARCHAR(255) NOT NULL,
	received_at TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_to TIMESTAMP WITH TIME ZONE NOT NULL,
	used_at TIMESTAMP WITH TIME ZONE,
	order_id BIGINT,
	min_amount_snapshot NUMERIC(18, 6) NOT NULL,
	discount_amount_snapshot NUMERIC(18, 6),
	discount_rate_snapshot NUMERIC(18, 6),
	max_discount_snapshot NUMERIC(18, 6),
	coupon_name_snapshot VARCHAR(255) NOT NULL,
	coupon_type_snapshot VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (coupon_code),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(template_id) REFERENCES coupon_template (id)
)

;

CREATE TABLE user_message (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	message_type VARCHAR(255) NOT NULL,
	title VARCHAR(255) NOT NULL,
	content TEXT NOT NULL,
	biz_type VARCHAR(255),
	biz_id BIGINT,
	is_read BOOLEAN NOT NULL,
	read_at TIMESTAMP WITH TIME ZONE,
	is_deleted BOOLEAN NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES "user" (id)
)

;

CREATE TABLE user_vehicle (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	plate_number VARCHAR(255) NOT NULL,
	vehicle_name VARCHAR(255),
	brand VARCHAR(255),
	model VARCHAR(255),
	battery_capacity NUMERIC(18, 6) NOT NULL,
	current_soc BIGINT NOT NULL,
	soc_source VARCHAR(255) NOT NULL,
	soc_updated_at TIMESTAMP WITH TIME ZONE,
	is_default BOOLEAN NOT NULL,
	status VARCHAR(255) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (plate_number),
	CHECK (battery_capacity > 0),
	CHECK (current_soc BETWEEN 0 AND 100),
	FOREIGN KEY(user_id) REFERENCES "user" (id)
)

;

CREATE TABLE charging_price_plan (
	id BIGSERIAL NOT NULL,
	plan_name VARCHAR(255) NOT NULL,
	station_id BIGINT NOT NULL,
	pile_id BIGINT,
	version VARCHAR(255) NOT NULL,
	effective_from TIMESTAMP WITH TIME ZONE NOT NULL,
	effective_to TIMESTAMP WITH TIME ZONE,
	status VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id),
	FOREIGN KEY(pile_id) REFERENCES charging_pile (id)
)

;

CREATE TABLE coupon_event_log (
	id BIGSERIAL NOT NULL,
	user_id BIGINT NOT NULL,
	rule_id BIGINT NOT NULL,
	event_type VARCHAR(255) NOT NULL,
	triggered BOOLEAN NOT NULL,
	user_coupon_id BIGINT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(rule_id) REFERENCES coupon_event_rule (id),
	FOREIGN KEY(user_coupon_id) REFERENCES user_coupon (id)
)

;

CREATE TABLE occupancy_fee_tier (
	id BIGSERIAL NOT NULL,
	rule_id BIGINT NOT NULL,
	start_minute BIGINT NOT NULL,
	end_minute BIGINT,
	price_per_minute NUMERIC(18, 6) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(rule_id) REFERENCES occupancy_fee_rule (id)
)

;

CREATE TABLE reservation (
	id BIGSERIAL NOT NULL,
	reservation_no VARCHAR(255) NOT NULL,
	user_id BIGINT NOT NULL,
	vehicle_id BIGINT NOT NULL,
	station_id BIGINT NOT NULL,
	pile_id BIGINT NOT NULL,
	reservation_time TIMESTAMP WITH TIME ZONE NOT NULL,
	expire_time TIMESTAMP WITH TIME ZONE NOT NULL,
	arrived_at TIMESTAMP WITH TIME ZONE,
	status VARCHAR(255) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	cancelled_at TIMESTAMP WITH TIME ZONE,
	credit_penalty_applied BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (reservation_no),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(vehicle_id) REFERENCES user_vehicle (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id),
	FOREIGN KEY(pile_id) REFERENCES charging_pile (id)
)

;

CREATE TABLE charging_price_period (
	id BIGSERIAL NOT NULL,
	plan_id BIGINT NOT NULL,
	start_time VARCHAR(255) NOT NULL,
	end_time VARCHAR(255) NOT NULL,
	electricity_price NUMERIC(18, 6) NOT NULL,
	service_price NUMERIC(18, 6) NOT NULL,
	sort_no BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CHECK (electricity_price >= 0),
	CHECK (service_price >= 0),
	FOREIGN KEY(plan_id) REFERENCES charging_price_plan (id)
)

;

CREATE TABLE charging_session (
	id BIGSERIAL NOT NULL,
	session_no VARCHAR(255) NOT NULL,
	user_id BIGINT NOT NULL,
	vehicle_id BIGINT NOT NULL,
	station_id BIGINT NOT NULL,
	pile_id BIGINT NOT NULL,
	reservation_id BIGINT,
	price_plan_id BIGINT NOT NULL,
	occupancy_rule_id BIGINT NOT NULL,
	start_soc BIGINT NOT NULL,
	target_soc BIGINT NOT NULL,
	current_soc BIGINT NOT NULL,
	end_soc BIGINT,
	energy_kwh NUMERIC(18, 6) NOT NULL,
	start_time TIMESTAMP WITH TIME ZONE NOT NULL,
	charge_end_time TIMESTAMP WITH TIME ZONE,
	current_power_kw NUMERIC(18, 6) NOT NULL,
	free_leave_deadline TIMESTAMP WITH TIME ZONE,
	leave_time TIMESTAMP WITH TIME ZONE,
	status VARCHAR(255) NOT NULL,
	stop_reason VARCHAR(255),
	abnormal_reason TEXT,
	updated_at TIMESTAMP WITH TIME ZONE,
	price_snapshot JSON NOT NULL,
	occupancy_snapshot JSON NOT NULL,
	battery_capacity NUMERIC(18, 6) NOT NULL,
	meter_sequence BIGINT NOT NULL,
	telemetry_at TIMESTAMP WITH TIME ZONE,
	fee_segments JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (session_no),
	CHECK (target_soc IN (80,90,100)),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(vehicle_id) REFERENCES user_vehicle (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id),
	FOREIGN KEY(pile_id) REFERENCES charging_pile (id),
	FOREIGN KEY(reservation_id) REFERENCES reservation (id),
	FOREIGN KEY(price_plan_id) REFERENCES charging_price_plan (id),
	FOREIGN KEY(occupancy_rule_id) REFERENCES occupancy_fee_rule (id)
)

;

CREATE TABLE charging_order (
	id BIGSERIAL NOT NULL,
	order_no VARCHAR(255) NOT NULL,
	user_id BIGINT NOT NULL,
	session_id BIGINT NOT NULL,
	vehicle_id BIGINT NOT NULL,
	station_id BIGINT NOT NULL,
	pile_id BIGINT NOT NULL,
	start_time TIMESTAMP WITH TIME ZONE NOT NULL,
	charge_end_time TIMESTAMP WITH TIME ZONE NOT NULL,
	leave_time TIMESTAMP WITH TIME ZONE NOT NULL,
	duration_minutes BIGINT NOT NULL,
	energy_kwh NUMERIC(18, 6) NOT NULL,
	electricity_fee NUMERIC(18, 6) NOT NULL,
	service_fee NUMERIC(18, 6) NOT NULL,
	occupancy_fee NUMERIC(18, 6) NOT NULL,
	original_amount NUMERIC(18, 6) NOT NULL,
	user_coupon_id BIGINT,
	coupon_discount NUMERIC(18, 6) NOT NULL,
	points_change BIGINT NOT NULL,
	credit_change BIGINT NOT NULL,
	payable_amount NUMERIC(18, 6) NOT NULL,
	order_status VARCHAR(255) NOT NULL,
	payment_status VARCHAR(255) NOT NULL,
	overdue_at TIMESTAMP WITH TIME ZONE,
	paid_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (order_no),
	UNIQUE (session_id),
	CHECK (payable_amount >= 0),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(session_id) REFERENCES charging_session (id),
	FOREIGN KEY(vehicle_id) REFERENCES user_vehicle (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id),
	FOREIGN KEY(pile_id) REFERENCES charging_pile (id),
	FOREIGN KEY(user_coupon_id) REFERENCES user_coupon (id)
)

;

CREATE TABLE fault_record (
	id BIGSERIAL NOT NULL,
	fault_no VARCHAR(255) NOT NULL,
	pile_id BIGINT NOT NULL,
	station_id BIGINT NOT NULL,
	source_type VARCHAR(255) NOT NULL,
	reporter_user_id BIGINT,
	session_id BIGINT,
	fault_type VARCHAR(255) NOT NULL,
	fault_description TEXT NOT NULL,
	fault_time TIMESTAMP WITH TIME ZONE NOT NULL,
	status VARCHAR(255) NOT NULL,
	handler_id BIGINT,
	handle_note TEXT,
	resolved_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (fault_no),
	FOREIGN KEY(pile_id) REFERENCES charging_pile (id),
	FOREIGN KEY(station_id) REFERENCES charging_station (id),
	FOREIGN KEY(reporter_user_id) REFERENCES "user" (id),
	FOREIGN KEY(session_id) REFERENCES charging_session (id)
)

;

CREATE TABLE after_sales_application (
	id BIGSERIAL NOT NULL,
	after_sales_no VARCHAR(255) NOT NULL,
	user_id BIGINT NOT NULL,
	order_id BIGINT NOT NULL,
	type VARCHAR(255) NOT NULL,
	reason TEXT NOT NULL,
	evidence JSON,
	requested_amount NUMERIC(18, 6) NOT NULL,
	status VARCHAR(255) NOT NULL,
	handler_id BIGINT,
	handle_result TEXT,
	handled_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (after_sales_no),
	FOREIGN KEY(user_id) REFERENCES "user" (id),
	FOREIGN KEY(order_id) REFERENCES charging_order (id)
)

;

CREATE TABLE order_fee_detail (
	id BIGSERIAL NOT NULL,
	order_id BIGINT NOT NULL,
	fee_type VARCHAR(255) NOT NULL,
	period_start TIMESTAMP WITH TIME ZONE NOT NULL,
	period_end TIMESTAMP WITH TIME ZONE NOT NULL,
	quantity NUMERIC(18, 6) NOT NULL,
	unit_price NUMERIC(18, 6) NOT NULL,
	amount NUMERIC(18, 6) NOT NULL,
	description TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(order_id) REFERENCES charging_order (id)
)

;

CREATE TABLE payment_record (
	id BIGSERIAL NOT NULL,
	payment_no VARCHAR(255) NOT NULL,
	order_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	pay_method VARCHAR(255) NOT NULL,
	pay_amount NUMERIC(18, 6) NOT NULL,
	status VARCHAR(255) NOT NULL,
	transaction_no VARCHAR(255) NOT NULL,
	paid_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (payment_no),
	UNIQUE (order_id),
	FOREIGN KEY(order_id) REFERENCES charging_order (id),
	FOREIGN KEY(user_id) REFERENCES "user" (id)
)

;

CREATE TABLE refund_record (
	id BIGSERIAL NOT NULL,
	refund_no VARCHAR(255) NOT NULL,
	after_sales_id BIGINT NOT NULL,
	order_id BIGINT NOT NULL,
	payment_id BIGINT NOT NULL,
	refund_type VARCHAR(255) NOT NULL,
	refund_method VARCHAR(255) NOT NULL,
	refund_amount NUMERIC(18, 6) NOT NULL,
	refund_transaction_no VARCHAR(255) NOT NULL,
	coupon_returned BOOLEAN NOT NULL,
	status VARCHAR(255) NOT NULL,
	failure_reason TEXT,
	refunded_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (refund_no),
	UNIQUE (after_sales_id),
	CHECK (refund_amount > 0),
	FOREIGN KEY(after_sales_id) REFERENCES after_sales_application (id),
	FOREIGN KEY(order_id) REFERENCES charging_order (id),
	FOREIGN KEY(payment_id) REFERENCES payment_record (id)
)

;
CREATE INDEX ix_charging_station_city_status ON charging_station (city, status);
CREATE INDEX ix_login_log_created_at ON login_log (created_at);
CREATE INDEX ix_charging_pile_station_id_status_pile_type ON charging_pile (station_id, status, pile_type);
CREATE INDEX ix_credit_record_change_type_biz_id_user_id ON credit_record (change_type, biz_id, user_id);
CREATE INDEX ix_credit_record_user_id_created_at ON credit_record (user_id, created_at);
CREATE INDEX ix_operation_log_created_at ON operation_log (created_at);
CREATE INDEX ix_points_record_user_id_created_at ON points_record (user_id, created_at);
CREATE INDEX ix_station_availability_watch_station_id_status_pile_type ON station_availability_watch (station_id, status, pile_type);
CREATE INDEX ix_station_availability_watch_status_id ON station_availability_watch (status, id);
CREATE INDEX ix_user_coupon_status_valid_to ON user_coupon (status, valid_to);
CREATE INDEX ix_user_coupon_template_id_user_id ON user_coupon (template_id, user_id);
CREATE INDEX ix_user_coupon_user_id_status ON user_coupon (user_id, status);
CREATE INDEX ix_user_message_user_id_is_deleted_is_read ON user_message (user_id, is_deleted, is_read);
CREATE UNIQUE INDEX uq_default_vehicle ON user_vehicle (user_id) WHERE is_default AND status = 'NORMAL';
CREATE INDEX ix_charging_price_plan_station_id_status_pile_id_effective_from ON charging_price_plan (station_id, status, pile_id, effective_from);
CREATE INDEX ix_coupon_event_log_user_id_rule_id_created_at ON coupon_event_log (user_id, rule_id, created_at);
CREATE INDEX ix_reservation_status_expire_time ON reservation (status, expire_time);
CREATE INDEX ix_reservation_user_id_created_at ON reservation (user_id, created_at);
CREATE UNIQUE INDEX uq_active_reservation_pile ON reservation (pile_id) WHERE status IN ('WAITING','ARRIVED','CHARGING');
CREATE UNIQUE INDEX uq_active_reservation_user ON reservation (user_id) WHERE status IN ('WAITING','ARRIVED','CHARGING');
CREATE INDEX ix_charging_session_status_id ON charging_session (status, id);
CREATE INDEX ix_charging_session_status_updated_at ON charging_session (status, updated_at);
CREATE UNIQUE INDEX uq_active_pile_session ON charging_session (pile_id) WHERE status IN ('STARTING','CHARGING','STOPPING','CHARGE_FINISHED','OCCUPYING','SETTLING','ABNORMAL') AND leave_time IS NULL;
CREATE UNIQUE INDEX uq_active_user_session ON charging_session (user_id) WHERE status IN ('STARTING','CHARGING','STOPPING','CHARGE_FINISHED','OCCUPYING','SETTLING','ABNORMAL') AND leave_time IS NULL;
CREATE INDEX ix_charging_order_created_at ON charging_order (created_at);
CREATE INDEX ix_charging_order_payment_status_overdue_at ON charging_order (payment_status, overdue_at);
CREATE INDEX ix_charging_order_station_id_created_at ON charging_order (station_id, created_at);
CREATE INDEX ix_charging_order_user_id_created_at ON charging_order (user_id, created_at);
CREATE INDEX ix_fault_record_station_id_status ON fault_record (station_id, status);
CREATE INDEX ix_after_sales_application_user_id_status ON after_sales_application (user_id, status);
CREATE INDEX ix_order_fee_detail_order_id ON order_fee_detail (order_id);
CREATE INDEX ix_payment_record_paid_at ON payment_record (paid_at);
CREATE INDEX ix_refund_record_order_id ON refund_record (order_id);
CREATE INDEX ix_refund_record_refunded_at ON refund_record (refunded_at);

<?php
/**
 * Plugin Name: Content Studio Connect
 * Description: Connects this WooCommerce store to AI Content Studio in one click — no need to generate REST API keys yourself.
 * Version: 0.1.0
 * Requires PHP: 7.4
 * Requires Plugins: woocommerce
 * License: GPL-2.0-or-later
 *
 * Deliberately thin, per 13_WOOCOMMERCE_PLUGIN_ARCHITECTURE.md's
 * "Thin-Plugin Principle" — this plugin only handles the connection
 * handshake. Generation, planning, publishing, analytics, and billing all
 * stay in the SaaS backend; nothing here talks to any AI provider.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit; // No direct access.
}

define( 'CS_CONNECT_VERSION', '0.1.0' );

// Must match the backend's own CS_PUBLIC_API_BASE_URL (see
// backend/.env.example). Currently the personal-use VPS deployment — swap
// to the real commercial domain once one is bought (see deployment notes).
if ( ! defined( 'CS_CONNECT_API_BASE_URL' ) ) {
	define( 'CS_CONNECT_API_BASE_URL', 'https://api-ng0w75q8muzknqpgaz3dvj6s.169.58.234.8.sslip.io/api/v1' );
}

// Where the "finish setup: connect Facebook & Instagram" link sends the
// store owner — must be a real top-level browser tab, never an iframe:
// Meta's OAuth dialog explicitly blocks iframe embedding, and this plugin
// makes no attempt to replicate that flow in PHP (see plan notes).
if ( ! defined( 'CS_CONNECT_WEB_APP_URL' ) ) {
	define( 'CS_CONNECT_WEB_APP_URL', 'https://vmi3532555.contaboserver.net/quick-start' );
}

add_action( 'admin_menu', 'cs_connect_register_menu' );

/**
 * Registers the settings screen under WooCommerce's own menu rather than a
 * new top-level item — keeps this discoverable where a WooCommerce admin
 * already looks for store-integration settings.
 */
function cs_connect_register_menu() {
	add_submenu_page(
		'woocommerce',
		__( 'Content Studio', 'content-studio-connect' ),
		__( 'Content Studio', 'content-studio-connect' ),
		'manage_woocommerce',
		'content-studio-connect',
		'cs_connect_render_settings_page'
	);
}

function cs_connect_render_settings_page() {
	if ( ! current_user_can( 'manage_woocommerce' ) ) {
		return;
	}

	$connected = get_option( 'cs_connect_connected', false );
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'Content Studio', 'content-studio-connect' ); ?></h1>

		<?php cs_connect_render_notices(); ?>

		<?php if ( $connected ) : ?>
			<p><strong><?php esc_html_e( 'This store is connected.', 'content-studio-connect' ); ?></strong></p>
			<p>
				<a
					href="<?php echo esc_url( CS_CONNECT_WEB_APP_URL ); ?>"
					target="_blank"
					rel="noopener noreferrer"
					class="button button-primary"
				>
					<?php esc_html_e( 'Finish setup: Connect Facebook & Instagram', 'content-studio-connect' ); ?>
				</a>
			</p>
			<p class="description">
				<?php esc_html_e( 'Opens Content Studio in a new tab — log in there (if not already) to finish connecting your social accounts.', 'content-studio-connect' ); ?>
			</p>
		<?php else : ?>
			<p>
				<?php esc_html_e( 'Paste the pairing code from your Content Studio account below — this store will connect automatically, no need to generate API keys yourself.', 'content-studio-connect' ); ?>
			</p>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<?php wp_nonce_field( 'cs_connect_pair', 'cs_connect_nonce' ); ?>
				<input type="hidden" name="action" value="cs_connect_pair" />
				<table class="form-table" role="presentation">
					<tr>
						<th scope="row">
							<label for="cs_connect_pairing_token"><?php esc_html_e( 'Pairing code', 'content-studio-connect' ); ?></label>
						</th>
						<td>
							<input
								type="text"
								id="cs_connect_pairing_token"
								name="pairing_token"
								class="regular-text"
								autocomplete="off"
								required
							/>
							<p class="description">
								<?php esc_html_e( 'Generated from Content Studio\'s eCommerce page — expires 30 minutes after it\'s generated.', 'content-studio-connect' ); ?>
							</p>
						</td>
					</tr>
				</table>
				<?php submit_button( __( 'Connect', 'content-studio-connect' ) ); ?>
			</form>
		<?php endif; ?>
	</div>
	<?php
}

function cs_connect_render_notices() {
	$error = get_transient( 'cs_connect_error' );
	if ( $error ) {
		delete_transient( 'cs_connect_error' );
		printf( '<div class="notice notice-error"><p>%s</p></div>', esc_html( $error ) );
	}

	if ( isset( $_GET['connected'] ) && '1' === $_GET['connected'] ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only query arg, no state change.
		printf( '<div class="notice notice-success"><p>%s</p></div>', esc_html__( 'Connected!', 'content-studio-connect' ) );
	}
}

add_action( 'admin_post_cs_connect_pair', 'cs_connect_handle_pair' );

/**
 * Handles the "Connect" button submit — generates a real WooCommerce REST
 * API key pair internally, then hands it to the backend alongside the
 * pairing code so it knows which Content Studio workspace to attach this
 * store to. Standard admin-post.php + nonce pattern, not a bespoke
 * CSRF mechanism.
 */
function cs_connect_handle_pair() {
	if ( ! current_user_can( 'manage_woocommerce' ) ) {
		wp_die( esc_html__( 'You do not have permission to do this.', 'content-studio-connect' ) );
	}
	check_admin_referer( 'cs_connect_pair', 'cs_connect_nonce' );

	$pairing_token = isset( $_POST['pairing_token'] ) ? sanitize_text_field( wp_unslash( $_POST['pairing_token'] ) ) : '';
	if ( '' === $pairing_token ) {
		cs_connect_fail( __( 'Please paste the pairing code.', 'content-studio-connect' ) );
	}

	if ( ! class_exists( 'WooCommerce' ) ) {
		cs_connect_fail( __( 'WooCommerce must be active to connect.', 'content-studio-connect' ) );
	}

	$keys = cs_connect_generate_api_keys();
	if ( is_wp_error( $keys ) ) {
		cs_connect_fail( $keys->get_error_message() );
	}

	$response = wp_remote_post(
		trailingslashit( CS_CONNECT_API_BASE_URL ) . 'commerce/connect/plugin',
		array(
			'timeout' => 20,
			'headers' => array( 'Content-Type' => 'application/json' ),
			'body'    => wp_json_encode(
				array(
					'pairing_token'   => $pairing_token,
					'store_domain'    => home_url(),
					'consumer_key'    => $keys['consumer_key'],
					'consumer_secret' => $keys['consumer_secret'],
				)
			),
		)
	);

	if ( is_wp_error( $response ) ) {
		cs_connect_fail( $response->get_error_message() );
	}

	$status_code = wp_remote_retrieve_response_code( $response );
	if ( $status_code < 200 || $status_code >= 300 ) {
		$body   = json_decode( wp_remote_retrieve_body( $response ), true );
		$detail = ( is_array( $body ) && isset( $body['detail'] ) && is_string( $body['detail'] ) )
			? $body['detail']
			: __( 'Connection failed — please generate a new pairing code and try again.', 'content-studio-connect' );
		cs_connect_fail( $detail );
	}

	update_option( 'cs_connect_connected', true );
	wp_safe_redirect( admin_url( 'admin.php?page=content-studio-connect&connected=1' ) );
	exit;
}

function cs_connect_fail( $message ) {
	set_transient( 'cs_connect_error', $message, 60 );
	wp_safe_redirect( admin_url( 'admin.php?page=content-studio-connect' ) );
	exit;
}

/**
 * Generates a real WooCommerce REST API key pair the same way WooCommerce's
 * own "Add Key" admin screen does internally — a direct insert into
 * WooCommerce's own keys table using WooCommerce's own hashing helpers —
 * so the store owner never has to visit that screen themselves.
 *
 * This is the one place in this plugin that reaches past WooCommerce's
 * public API into its internal DB schema rather than a documented public
 * function, since WooCommerce has no public "create a key for me"
 * function — only its own admin-UI code path does this insert. It has been
 * stable across WooCommerce versions for years, but hasn't been verified
 * against a live install in this build (no PHP/WordPress available in the
 * dev environment this was written in) — if "Connect" fails specifically
 * here, check WooCommerce → Settings → Advanced → REST API afterward to
 * confirm whether a key actually appears, and check this insert's column
 * list against the current `{prefix}woocommerce_api_keys` table schema.
 *
 * @return array{consumer_key: string, consumer_secret: string}|WP_Error
 */
function cs_connect_generate_api_keys() {
	global $wpdb;

	if ( ! function_exists( 'wc_rand_hash' ) || ! function_exists( 'wc_api_hash' ) ) {
		return new WP_Error(
			'cs_connect_missing_woocommerce',
			__( 'WooCommerce REST API support is unavailable on this site.', 'content-studio-connect' )
		);
	}

	$consumer_key    = 'ck_' . wc_rand_hash();
	$consumer_secret = 'cs_' . wc_rand_hash();

	$inserted = $wpdb->insert(
		$wpdb->prefix . 'woocommerce_api_keys',
		array(
			'user_id'         => get_current_user_id(),
			'description'     => 'Content Studio (' . gmdate( 'Y-m-d H:i:s' ) . ')',
			'permissions'     => 'read_write',
			'consumer_key'    => wc_api_hash( $consumer_key ),
			'consumer_secret' => $consumer_secret,
			'truncated_key'   => substr( $consumer_key, -7 ),
		),
		array( '%d', '%s', '%s', '%s', '%s', '%s' )
	);

	if ( ! $inserted ) {
		return new WP_Error(
			'cs_connect_key_insert_failed',
			__( 'Could not create a WooCommerce API key for this store.', 'content-studio-connect' )
		);
	}

	return array(
		'consumer_key'    => $consumer_key,
		'consumer_secret' => $consumer_secret,
	);
}

/**
 * Disconnecting removes the local "connected" flag and the API key this
 * plugin created — it does not (and cannot) reach into Content Studio to
 * delete the connection there too; that's a manual step on the backend
 * side today (see modules/commerce/service.py — no revoke endpoint exists
 * yet). Deliberately out of scope for this first slice.
 */
register_uninstall_hook( __FILE__, 'cs_connect_uninstall' );

function cs_connect_uninstall() {
	delete_option( 'cs_connect_connected' );
}

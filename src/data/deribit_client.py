"""Deribit REST API client."""

from typing import Any, cast

import aiohttp


class DeribitError(Exception):
    """Deribit API error."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Deribit error {code}: {message}")


class DeribitClient:
    """Async client for Deribit REST API."""

    def __init__(
        self,
        base_url: str = "https://www.deribit.com",
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        """Initialize Deribit client.

        Args:
            base_url: Deribit API base URL.
            api_key: API key for authentication.
            api_secret: API secret for authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self.access_token is not None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is not None and self._session.closed:
            self._session = None  # Clear stale reference
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        private: bool = False,
        _retry: bool = True,
    ) -> Any:
        """Make API request.

        Args:
            method: HTTP method (GET, POST).
            endpoint: API endpoint path.
            params: Query parameters.
            private: Whether this is a private endpoint requiring auth.
            _retry: Internal flag to prevent infinite retry loops.

        Returns:
            Response result.

        Raises:
            DeribitError: If API returns an error.
        """
        session = await self._get_session()
        url = f"{self.base_url}/api/v2{endpoint}"

        headers = {}
        if private and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        async with session.request(method, url, params=params, headers=headers) as response:
            data = await response.json()

            if "error" in data:
                error = data["error"]
                error_code = error.get("code", -1)

                # 13009 = unauthorized (token expired)
                # Auto-refresh and retry once for private endpoints
                if error_code == 13009 and private and _retry:
                    await self._refresh_access_token()
                    return await self._request(method, endpoint, params, private, _retry=False)

                raise DeribitError(error_code, error.get("message", "Unknown error"))

            return data.get("result")

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using refresh_token or re-authenticate.

        Deribit access tokens expire after ~15 minutes. This method attempts
        to refresh using the refresh_token if available, otherwise falls back
        to full re-authentication.
        """
        if self.refresh_token:
            try:
                params = {
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                }
                result = await self._request("GET", "/public/auth", params, _retry=False)
                self.access_token = result["access_token"]
                self.refresh_token = result.get("refresh_token")
                return
            except DeribitError:
                # Refresh token also expired, fall through to re-auth
                pass

        # Fall back to full re-authentication (with _retry=False to prevent loops)
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.api_secret,
        }
        result = await self._request("GET", "/public/auth", params, _retry=False)
        self.access_token = result["access_token"]
        self.refresh_token = result.get("refresh_token")

    async def authenticate(self) -> None:
        """Authenticate with Deribit API.

        Uses client credentials grant type.
        """
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.api_secret,
        }

        result = await self._request("GET", "/public/auth", params)

        self.access_token = result["access_token"]
        self.refresh_token = result.get("refresh_token")

    async def get_index_price(self, index_name: str = "btc_usd") -> float:
        """Get current index price.

        Args:
            index_name: Index name (btc_usd, eth_usd).

        Returns:
            Current index price.
        """
        result = await self._request("GET", "/public/get_index_price", {"index_name": index_name})
        return cast(float, result["index_price"])

    async def get_instruments(
        self,
        currency: str = "BTC",
        kind: str = "option",
        expired: bool = False,
    ) -> list[dict[str, Any]]:
        """Get available instruments.

        Args:
            currency: Currency (BTC, ETH).
            kind: Instrument kind (option, future).
            expired: Include expired instruments.

        Returns:
            List of instruments.
        """
        params = {
            "currency": currency,
            "kind": kind,
            "expired": str(expired).lower(),
        }
        return cast(list[dict[str, Any]], await self._request("GET", "/public/get_instruments", params))

    async def get_order_book(
        self,
        instrument_name: str,
        depth: int = 10,
    ) -> dict[str, Any]:
        """Get order book for instrument.

        Args:
            instrument_name: Instrument name.
            depth: Order book depth.

        Returns:
            Order book data with bids/asks.
        """
        params = {
            "instrument_name": instrument_name,
            "depth": depth,
        }
        return cast(dict[str, Any], await self._request("GET", "/public/get_order_book", params))

    async def get_ticker(self, instrument_name: str) -> dict[str, Any]:
        """Get ticker data for instrument.

        Args:
            instrument_name: Instrument name.

        Returns:
            Ticker data including mark price, greeks, IV.
        """
        params = {"instrument_name": instrument_name}
        return cast(dict[str, Any], await self._request("GET", "/public/ticker", params))

    async def get_book_summary_by_currency(
        self,
        currency: str = "BTC",
        kind: str = "option",
    ) -> list[dict[str, Any]]:
        """Get book summary for all instruments of a currency.

        Args:
            currency: Currency (BTC, ETH).
            kind: Instrument kind (option, future).

        Returns:
            List of book summaries.
        """
        params = {"currency": currency, "kind": kind}
        return cast(list[dict[str, Any]], await self._request("GET", "/public/get_book_summary_by_currency", params))

    async def get_account_summary(self, currency: str = "BTC") -> dict[str, Any]:
        """Get account summary.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            Account summary with equity, balance, margin info.
        """
        params = {"currency": currency}
        return cast(dict[str, Any], await self._request("GET", "/private/get_account_summary", params, private=True))

    async def get_positions(
        self,
        currency: str = "BTC",
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get open positions.

        Args:
            currency: Currency (BTC, ETH).
            kind: Filter by instrument kind (option, future).

        Returns:
            List of open positions with Greeks.
        """
        params: dict[str, Any] = {"currency": currency}
        if kind:
            params["kind"] = kind
        return cast(list[dict[str, Any]], await self._request("GET", "/private/get_positions", params, private=True))

    async def buy(
        self,
        instrument_name: str,
        amount: float,
        price: float | None = None,
        order_type: str = "limit",
    ) -> dict[str, Any]:
        """Place a buy order.

        Args:
            instrument_name: Instrument to buy.
            amount: Amount in contracts.
            price: Limit price (required for limit orders).
            order_type: Order type (limit, market).

        Returns:
            Order result.
        """
        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": order_type,
        }
        if price is not None:
            params["price"] = price
        return cast(dict[str, Any], await self._request("GET", "/private/buy", params, private=True))

    async def sell(
        self,
        instrument_name: str,
        amount: float,
        price: float | None = None,
        order_type: str = "limit",
    ) -> dict[str, Any]:
        """Place a sell order.

        Args:
            instrument_name: Instrument to sell.
            amount: Amount in contracts.
            price: Limit price (required for limit orders).
            order_type: Order type (limit, market).

        Returns:
            Order result.
        """
        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": order_type,
        }
        if price is not None:
            params["price"] = price
        return cast(dict[str, Any], await self._request("GET", "/private/sell", params, private=True))

    async def cancel(self, order_id: str) -> dict[str, Any]:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            Cancellation result.
        """
        params = {"order_id": order_id}
        return cast(dict[str, Any], await self._request("GET", "/private/cancel", params, private=True))

    async def get_open_orders(
        self,
        currency: str = "BTC",
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get open orders.

        Args:
            currency: Currency (BTC, ETH).
            kind: Filter by instrument kind.

        Returns:
            List of open orders.
        """
        params: dict[str, Any] = {"currency": currency}
        if kind:
            params["kind"] = kind
        return cast(list[dict[str, Any]], await self._request("GET", "/private/get_open_orders_by_currency", params, private=True))

    async def get_volatility_index(
        self,
        currency: str = "BTC",
        resolution: int = 3600,
        start_timestamp: int = 0,
        end_timestamp: int = 9999999999999,
    ) -> list[list[float]]:
        """Get historical volatility index (DVOL) data.

        Args:
            currency: Currency (BTC, ETH).
            resolution: Candle resolution in seconds.
            start_timestamp: Start time in milliseconds.
            end_timestamp: End time in milliseconds.

        Returns:
            List of OHLC data [timestamp, open, high, low, close].
        """
        params = {
            "currency": currency,
            "resolution": resolution,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        result = await self._request("GET", "/public/get_volatility_index_data", params)
        return cast(list[list[float]], result.get("data", []))

    async def get_current_dvol(self, currency: str = "BTC") -> float:
        """Get current DVOL value.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            Current DVOL value.
        """
        # Try index price first (works on testnet)
        try:
            index_name = f"dvol_{currency.lower()}"
            result = await self._request("GET", "/public/get_index_price", {"index_name": index_name})
            return cast(float, result["index_price"])
        except DeribitError:
            # Fallback to volatility index data (works on production)
            import time
            now_ms = int(time.time() * 1000)
            # Get last hour of data
            start_ms = now_ms - 3600000
            dvol_data = await self.get_volatility_index(
                currency=currency,
                resolution=3600,
                start_timestamp=start_ms,
                end_timestamp=now_ms,
            )
            if dvol_data:
                # Return close value from latest candle
                return dvol_data[-1][4] if len(dvol_data[-1]) > 4 else dvol_data[-1][1]
            raise DeribitError(-1, "No DVOL data available")

    async def get_tradingview_chart_data(
        self,
        instrument_name: str,
        resolution: str = "1D",
        start_timestamp: int = 0,
        end_timestamp: int = 9999999999999,
    ) -> dict[str, Any]:
        """Get OHLCV chart data for an instrument.

        Args:
            instrument_name: Instrument name (e.g., BTC-PERPETUAL).
            resolution: Candle resolution (1, 3, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1D).
            start_timestamp: Start time in milliseconds.
            end_timestamp: End time in milliseconds.

        Returns:
            Dict with ticks, open, high, low, close, volume arrays.
        """
        params = {
            "instrument_name": instrument_name,
            "resolution": resolution,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        return cast(dict[str, Any], await self._request("GET", "/public/get_tradingview_chart_data", params))

    async def get_historical_volatility(
        self,
        currency: str = "BTC",
    ) -> list[list[float]]:
        """Get historical volatility data.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            List of [timestamp, volatility] pairs.
        """
        params = {"currency": currency}
        return cast(list[list[float]], await self._request("GET", "/public/get_historical_volatility", params))

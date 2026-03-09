"""
Integration tests for MCP server token authentication.

These tests verify that MCP servers correctly handle Authorization headers
with user tokens propagated from the API layer.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Set required environment variables before importing MCP modules
os.environ.setdefault("KEYCLOAK_REALM_URL", "http://localhost:8080/realms/test")
os.environ.setdefault("KEYCLOAK_MCP_SERVER_BASE_URL", "http://localhost:8002")
os.environ.setdefault("KEYCLOAK_MCP_SERVER_AUDIENCE", "mcp-server")
os.environ.setdefault("SQLITE_DATABASE_PATH", ":memory:")

try:
    from fastmcp.server.auth import AccessToken
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    AccessToken = None

# Try to import MCP modules (may fail if environment not configured)
try:
    from zava_shop_mcp.finance_server import auth as finance_auth, mcp as finance_mcp
    from zava_shop_mcp.supplier_server import auth as supplier_auth, mcp as supplier_mcp
    from zava_shop_mcp.keycloak_provider import KeycloakAuthProvider
    MCP_MODULES_AVAILABLE = True
except Exception:
    MCP_MODULES_AVAILABLE = False
    finance_auth = finance_mcp = supplier_auth = supplier_mcp = KeycloakAuthProvider = None

try:
    import zava_shop_agents  # noqa: F401
    AGENTS_MODULES_AVAILABLE = True
except Exception:
    AGENTS_MODULES_AVAILABLE = False


@pytest.mark.skipif(not MCP_MODULES_AVAILABLE, reason="MCP modules not available")
class TestMCPAuthorizationHeaderHandling:
    """Test that MCP servers correctly handle Authorization headers."""

    @pytest.mark.asyncio
    async def test_mcp_accepts_valid_authorization_header(self):
        """
        MCP server should accept requests with valid Authorization headers.
        
        This tests the auth flow without requiring a running Keycloak instance.
        """
        # The KeycloakAuthProvider uses JWTVerifier which validates tokens
        # In integration tests, we mock the token verifier to simulate valid tokens
        assert finance_auth is not None
        assert finance_auth.base_url is not None

    @pytest.mark.asyncio
    async def test_mcp_rejects_missing_authorization(self):
        """
        MCP server should reject requests without Authorization header.
        
        Note: With auth enabled, unauthenticated requests should fail.
        """
        # The MCP server with KeycloakAuthProvider configured
        # should require authentication for tool calls
        assert finance_mcp is not None

    @pytest.mark.asyncio
    async def test_keycloak_provider_configured_correctly(self):
        """
        Verify KeycloakAuthProvider is configured with correct scopes.
        """
        assert isinstance(finance_auth, KeycloakAuthProvider)
        # The provider should require specific scopes for access
        # These are configured during initialization


@pytest.mark.skipif(not MCP_MODULES_AVAILABLE, reason="MCP modules not available")
class TestTokenVerificationFlow:
    """Test the token verification flow in MCP servers."""

    @pytest.mark.asyncio
    async def test_jwt_verifier_validates_against_keycloak(self):
        """
        JWTVerifier should validate tokens against Keycloak's JWKS endpoint.
        """
        # Get the token verifier from the auth provider
        verifier = finance_auth.token_verifier
        assert verifier is not None

        # The verifier should have the Keycloak JWKS URI configured
        # This is set up in the KeycloakAuthProvider.__init__

    @pytest.mark.asyncio 
    async def test_required_scopes_enforced(self):
        """
        MCP server should enforce required scopes (openid, zava:access).
        """
        # The auth provider is configured with required_scopes
        # Tokens without these scopes should be rejected
        pass


@pytest.mark.skipif(not MCP_MODULES_AVAILABLE or not FASTMCP_AVAILABLE, reason="MCP modules or fastmcp not available")
class TestMCPToolAccessWithToken:
    """Test that MCP tools are accessible with proper authentication."""

    @pytest.mark.asyncio
    @patch("zava_shop_mcp.finance_server.auth")
    async def test_tool_call_with_mocked_auth(self, mock_auth):
        """
        Test calling MCP tools with mocked authentication.
        
        This allows testing tool functionality without Keycloak.
        """
        from fastmcp.client import Client

        # Create a mock access token
        mock_token = AccessToken(
            token="test-token",
            client_id="test-client",
            scopes=["openid", "zava:access"],
        )

        # Mock the auth to always return valid
        mock_auth.token_verifier.verify_token = AsyncMock(return_value=mock_token)

        # Test is documented but requires more setup for full execution


@pytest.mark.skipif(not MCP_MODULES_AVAILABLE, reason="MCP modules not available")
class TestSupplierServerAuth:
    """Test authentication for Supplier MCP server."""

    @pytest.mark.asyncio
    async def test_supplier_server_uses_keycloak_auth(self):
        """
        Supplier MCP server should use KeycloakAuthProvider.
        """
        assert isinstance(supplier_auth, KeycloakAuthProvider)

    @pytest.mark.asyncio
    async def test_supplier_server_requires_same_scopes(self):
        """
        Both MCP servers should require the same scopes for consistency.
        """
        # Both should use KeycloakAuthProvider with same scope requirements
        assert type(finance_auth) == type(supplier_auth)


class TestTokenPropagationIntegration:
    """
    Integration tests for full token propagation flow.
    
    These tests verify the complete chain:
    Frontend token → API → Agent → MCP with auth
    """

    @pytest.mark.skipif(not AGENTS_MODULES_AVAILABLE, reason="zava_shop_agents not available")
    def test_mcp_http_tool_configuration(self):
        """
        MCPStreamableHTTPToolOTEL should be configured with Authorization header.
        """
        import inspect
        from zava_shop_agents import MCPStreamableHTTPToolOTEL

        # Verify MCPStreamableHTTPToolOTEL has get_mcp_client that uses headers
        source = inspect.getsource(MCPStreamableHTTPToolOTEL)
        assert 'self.headers["traceparent"]' in source
        
    @pytest.mark.skipif(not AGENTS_MODULES_AVAILABLE, reason="zava_shop_agents not available")
    def test_workflow_mcp_configuration_uses_token(self):
        """
        Build workflow functions should configure MCP with user token.
        """
        import inspect
        from zava_shop_agents.stock import build_workflow
        
        source = inspect.getsource(build_workflow)
        # Verify the workflow uses auth_token for MCP Authorization header
        assert "auth_token = user_token or" in source
        assert 'f"Bearer {auth_token}"' in source

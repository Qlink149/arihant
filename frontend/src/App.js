import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Toaster } from './components/ui/sonner';

// Pages
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import VirtualCustomerPage from './pages/VirtualCustomerPage';
import DigitalTwinPage from './pages/DigitalTwinPage';
import SettingsPage from './pages/SettingsPage';

import SalesDashboardPage from './pages/SalesDashboardPage';
import MyDashboardPage from './pages/MyDashboardPage';
import MarketingDashboardPage from './pages/MarketingDashboardPage';
import DevDocsPage from './pages/DevDocsPage';
import NotificationsPage from './pages/NotificationsPage';
import PlatformOpsPage from './pages/PlatformOpsPage';

// Layout
import DashboardLayout from './components/layout/DashboardLayout';
import RouteProgress from './components/layout/RouteProgress';

// Protected Route Component
const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};

const AdminRoute = ({ children }) => {
  const { isAuthenticated, loading, user } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== 'admin') {
    return <Navigate to="/my-dashboard" replace />;
  }

  return children;
};

// Public Route Component (redirects to dashboard if logged in)
const PublicRoute = ({ children }) => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
};

function AppRoutes() {
  const { user } = useAuth();

  return (
    <>
      <RouteProgress />
      <Routes>
      {/* Public Routes */}
      <Route
        path="/login"
        element={
          <PublicRoute>
            <LoginPage />
          </PublicRoute>
        }
      />

      {/* Protected Routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="virtual-customer" element={<VirtualCustomerPage />} />
        <Route path="lead/:leadId" element={<DigitalTwinPage />} />
        <Route path="settings" element={<AdminRoute><SettingsPage /></AdminRoute>} />
        <Route path="sales-dashboard" element={<AdminRoute><SalesDashboardPage /></AdminRoute>} />
        <Route path="my-dashboard" element={<MyDashboardPage />} />
        <Route path="marketing-dashboard" element={<AdminRoute><MarketingDashboardPage /></AdminRoute>} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="developer-docs" element={<DevDocsPage />} />
        {user?.is_platform_operator && (
          <Route path="ops" element={<PlatformOpsPage />} />
        )}
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
    </>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
        <Toaster 
          position="top-right"
          toastOptions={{
            style: {
              background: '#1A1A1A',
              color: '#EDEDED',
              border: '1px solid rgba(255,255,255,0.1)'
            }
          }}
        />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;

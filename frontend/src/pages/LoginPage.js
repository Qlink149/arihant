import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { toast } from 'sonner';
import { Eye, EyeOff } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const LoginPage = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showTransition, setShowTransition] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();

  const [pwdModalOpen, setPwdModalOpen] = useState(false);
  const [pwdEmail, setPwdEmail] = useState('');
  const [pwdCurrent, setPwdCurrent] = useState('');
  const [pwdNew, setPwdNew] = useState('');
  const [pwdConfirm, setPwdConfirm] = useState('');
  const [pwdSaving, setPwdSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await login(email, password);
      setShowTransition(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid credentials');
      toast.error('Login failed. Please check your credentials.');
      setIsLoading(false);
    }
  };

  const handleChangePasswordFromLogin = async (e) => {
    e.preventDefault();
    if (pwdNew !== pwdConfirm) {
      toast.error('New password and confirmation do not match');
      return;
    }
    if (pwdNew.length < 8) {
      toast.error('New password must be at least 8 characters');
      return;
    }
    setPwdSaving(true);
    try {
      const formData = new URLSearchParams();
      formData.append('username', pwdEmail.trim());
      formData.append('password', pwdCurrent);

      const loginRes = await axios.post(`${API}/auth/login`, formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      const accessToken = loginRes.data?.access_token;
      if (!accessToken) {
        throw new Error('No access token returned');
      }

      await axios.put(
        `${API}/auth/password`,
        { current_password: pwdCurrent, new_password: pwdNew },
        { headers: { Authorization: `Bearer ${accessToken}` } }
      );

      toast.success('Password updated. Sign in with your new password.');
      setPwdModalOpen(false);
      setPwdEmail('');
      setPwdCurrent('');
      setPwdNew('');
      setPwdConfirm('');
      setEmail(pwdEmail.trim());
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || 'Could not update password';
      toast.error(typeof detail === 'string' ? detail : 'Could not update password');
    } finally {
      setPwdSaving(false);
    }
  };

  return (
    <div className="min-h-screen relative overflow-hidden bg-crm">
      <Dialog open={pwdModalOpen} onOpenChange={setPwdModalOpen}>
        <DialogContent className="bg-crm-elevated border-crm-border text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl text-crm-fg">Change password</DialogTitle>
            <p className="text-crm-fg-muted text-sm font-normal pt-1">
              Enter your account email and current password, then choose a new password. You will stay on this page and can sign in after.
            </p>
          </DialogHeader>
          <form onSubmit={handleChangePasswordFromLogin} className="space-y-4 pt-2">
            <div>
              <label className="block text-sm text-crm-fg-secondary mb-1">Email</label>
              <Input
                type="email"
                value={pwdEmail}
                onChange={(e) => setPwdEmail(e.target.value)}
                className="bg-crm-muted border-crm-border"
                required
                autoComplete="username"
              />
            </div>
            <div>
              <label className="block text-sm text-crm-fg-secondary mb-1">Current password</label>
              <Input
                type="password"
                value={pwdCurrent}
                onChange={(e) => setPwdCurrent(e.target.value)}
                className="bg-crm-muted border-crm-border"
                required
                autoComplete="current-password"
              />
            </div>
            <div>
              <label className="block text-sm text-crm-fg-secondary mb-1">New password</label>
              <Input
                type="password"
                value={pwdNew}
                onChange={(e) => setPwdNew(e.target.value)}
                className="bg-crm-muted border-crm-border"
                required
                minLength={8}
                autoComplete="new-password"
              />
            </div>
            <div>
              <label className="block text-sm text-crm-fg-secondary mb-1">Confirm new password</label>
              <Input
                type="password"
                value={pwdConfirm}
                onChange={(e) => setPwdConfirm(e.target.value)}
                className="bg-crm-muted border-crm-border"
                required
                autoComplete="new-password"
              />
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <Button type="button" variant="outline" className="border-white/20" onClick={() => setPwdModalOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pwdSaving} className="bg-[#C5A059] text-black hover:bg-[#E5C079]">
                {pwdSaving ? 'Updating…' : 'Update password'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <motion.div
        className="absolute inset-0 z-0"
        initial={{ scale: 1.1, y: 50 }}
        animate={{ scale: 1, y: 0 }}
        transition={{ duration: 2, ease: 'easeOut' }}
      >
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage: `url('https://images.unsplash.com/photo-1566393612878-2e68d73691a3?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzMjd8MHwxfHNlYXJjaHwxfHxjaGVubmFpJTIwY2l0eSUyMHNreWxpbmUlMjBuaWdodCUyMGx1eHVyeXxlbnwwfHx8fDE3NzMzMDU0MjF8MA&ixlib=rb-4.1.0&q=85')`,
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-[#0A0A0A] via-[#0A0A0A]/70 to-transparent" />
      </motion.div>

      <AnimatePresence>
        {showTransition && (
          <motion.div
            className="fixed inset-0 z-50 bg-crm flex flex-col items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.img
              src="https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/677bbae243140d29ba5e1fc0_Arihant%20W%20Logo.svg"
              alt="Arihant"
              className="h-16 mb-8"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            />

            <div className="relative w-full max-w-2xl h-48 overflow-hidden">
              <motion.div
                className="absolute bottom-0 w-full flex justify-center gap-2"
                initial={{ y: 200 }}
                animate={{ y: 0 }}
                transition={{ duration: 1.5, ease: 'easeOut', delay: 0.5 }}
              >
                {[...Array(12)].map((_, i) => (
                  <motion.div
                    key={i}
                    className="bg-gradient-to-t from-[#C5A059] to-[#C5A059]/30"
                    style={{
                      width: '30px',
                      height: `${60 + Math.random() * 140}px`,
                      borderRadius: '4px 4px 0 0',
                    }}
                    initial={{ y: 200 }}
                    animate={{ y: 0 }}
                    transition={{
                      duration: 1.2,
                      ease: 'easeOut',
                      delay: 0.5 + i * 0.1,
                    }}
                  />
                ))}
              </motion.div>
            </div>

            <motion.div
              className="mt-8 text-center"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 2 }}
            >
              <h1 className="font-serif text-3xl text-[#C5A059]">Welcome to Arihant</h1>
              <p className="text-crm-fg-secondary mt-2">Sales Intelligence Dashboard</p>
            </motion.div>

            <motion.div
              className="mt-8 h-1 w-48 bg-crm-elevated rounded-full overflow-hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 2 }}
            >
              <motion.div
                className="h-full bg-[#C5A059]"
                initial={{ width: '0%' }}
                animate={{ width: '100%' }}
                transition={{ duration: 1, delay: 2 }}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative z-10 min-h-screen flex items-center justify-center px-4">
        <motion.div
          className="w-full max-w-md"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.5 }}
        >
          <motion.div
            className="flex justify-center mb-8"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.8 }}
          >
            <img
              src="https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/677bbae243140d29ba5e1fc0_Arihant%20W%20Logo.svg"
              alt="Arihant Spaces"
              className="h-12"
              data-testid="login-logo"
            />
          </motion.div>

          <motion.div
            className="glass-card rounded-lg p-8"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 1 }}
          >
            <div className="text-center mb-8">
              <h1 className="font-serif text-2xl text-crm-fg" data-testid="login-title">
                Sales Intelligence
              </h1>
              <p className="text-crm-fg-secondary text-sm mt-2">Sign in to access your dashboard</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label className="block text-sm text-crm-fg-secondary mb-2">Email Address</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full h-12 px-4 bg-crm-muted border border-white/20 rounded-md text-white focus:border-[#C5A059] transition-colors"
                  placeholder="you@company.com"
                  required
                  data-testid="login-email-input"
                />
              </div>

              <div>
                <label className="block text-sm text-crm-fg-secondary mb-2">Password</label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full h-12 px-4 pr-12 bg-crm-muted border border-white/20 rounded-md text-white focus:border-[#C5A059] transition-colors"
                    placeholder="Enter your password"
                    required
                    data-testid="login-password-input"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-crm-fg-secondary hover:text-white transition-colors"
                    data-testid="toggle-password-btn"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="text-red-500 text-sm text-center"
                  data-testid="login-error"
                >
                  {error}
                </motion.div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="w-full h-12 bg-[#C5A059] text-black font-medium rounded-none hover:bg-[#E5C079] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="login-submit-btn"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    Signing in...
                  </span>
                ) : (
                  'Sign In'
                )}
              </button>

              <p className="text-center text-sm">
                <button
                  type="button"
                  onClick={() => setPwdModalOpen(true)}
                  className="text-[#C5A059] hover:text-[#E5C079] underline-offset-2 hover:underline"
                  data-testid="change-password-link"
                >
                  Change password
                </button>
                <span className="text-crm-fg-muted"> · </span>
                <span className="text-crm-fg-muted text-xs">Requires your current password</span>
              </p>
            </form>

            <p className="text-center text-crm-fg-muted text-xs mt-8">Arihant Spaces - Crafting Memorable Spaces Since 1995</p>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
};

export default LoginPage;

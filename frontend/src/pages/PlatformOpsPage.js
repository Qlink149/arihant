import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { platformOpsAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { toast } from 'sonner';
import { LogIn, Shield } from 'lucide-react';
import { Button } from '../components/ui/button';

const PlatformOpsPage = () => {
  const navigate = useNavigate();
  const { user, impersonateUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actingAs, setActingAs] = useState(null);

  useEffect(() => {
    if (!user?.is_platform_operator) {
      navigate('/dashboard', { replace: true });
      return;
    }
    loadUsers();
  }, [user, navigate]);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const { data } = await platformOpsAPI.listUsers();
      setUsers(data || []);
    } catch {
      toast.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  const handleLoginAs = async (target) => {
    setActingAs(target.id);
    try {
      await impersonateUser(target.id);
      toast.success(`Now viewing as ${target.full_name}`);
      navigate(target.role === 'admin' ? '/dashboard' : '/my-dashboard');
    } catch {
      toast.error('Impersonation failed');
    } finally {
      setActingAs(null);
    }
  };

  if (!user?.is_platform_operator) {
    return null;
  }

  return (
    <div className="space-y-6 max-w-5xl" data-testid="platform-ops-page">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-[#C5A059]/10 flex items-center justify-center">
          <Shield size={20} className="text-[#C5A059]" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold text-white">Ops</h1>
          <p className="text-[#52525B] text-sm">Login as any user to debug their experience</p>
        </div>
      </div>

      {loading ? (
        <div className="text-[#C5A059] animate-pulse py-12 text-center">Loading users...</div>
      ) : (
        <div className="bg-[#1A1A1A] border border-white/5 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[#52525B] text-left">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Role</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {users.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-[#52525B]">
                      No users found
                    </td>
                  </tr>
                ) : (
                  users.map((u) => (
                    <tr
                      key={u.id}
                      className="border-b border-white/5 hover:bg-white/[0.02]"
                      data-testid={`ops-user-${u.id}`}
                    >
                      <td className="px-4 py-3 text-white">{u.full_name}</td>
                      <td className="px-4 py-3 text-[#A1A1AA]">{u.email}</td>
                      <td className="px-4 py-3 text-[#A1A1AA] capitalize">{u.role}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full ${
                            u.is_active
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : 'bg-gray-500/20 text-gray-400'
                          }`}
                        >
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingAs === u.id}
                          onClick={() => handleLoginAs(u)}
                          className="border-[#C5A059]/30 text-[#C5A059] hover:bg-[#C5A059]/10"
                          data-testid={`login-as-${u.id}`}
                        >
                          <LogIn size={14} className="mr-1.5" />
                          {actingAs === u.id ? 'Signing in...' : 'Login as'}
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default PlatformOpsPage;

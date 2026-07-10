import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/chat_provider.dart';
import 'package:carhero/providers/agent_provider.dart';
import 'package:carhero/providers/session_provider.dart';
import 'package:carhero/screens/chat/widgets/session_tile.dart';

class ChatSidebar extends ConsumerWidget {
  const ChatSidebar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final sessionsAsync = ref.watch(sessionsProvider);
    final agentsAsync = ref.watch(agentsProvider);

    return Drawer(
      backgroundColor: Colors.white,
      child: SafeArea(
        child: Column(
          children: [
            // User header
            _UserHeader(
              email: auth.value?.email ?? '',
              name: auth.value?.name ?? '',
              onLogout: () {
                ref.read(authProvider.notifier).logout();
                Navigator.of(context).pop();
                context.go('/auth/login');
              },
            ),

            const SizedBox(height: 8),

            // New Chat button
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: () {
                    ref.read(chatProvider.notifier).newChat();
                    Navigator.of(context).pop();
                    context.go('/chat');
                  },
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('New Chat'),
                ),
              ),
            ),

            const SizedBox(height: 16),

            // Session history header
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'RECENT CHATS',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.gray500,
                    letterSpacing: 0.8,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 4),

            // Session list
            Expanded(
              flex: 3,
              child: sessionsAsync.when(
                loading: () => const Center(
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
                error: (e, _) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      'Could not load sessions',
                      style: TextStyle(color: AppTheme.gray500, fontSize: 13),
                    ),
                  ),
                ),
                data: (sessions) {
                  if (sessions.isEmpty) {
                    return Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(
                          'No chat history yet',
                          style: TextStyle(
                            color: AppTheme.gray400,
                            fontSize: 13,
                          ),
                        ),
                      ),
                    );
                  }
                  return ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    itemCount: sessions.length,
                    itemBuilder: (ctx, i) {
                      final session = sessions[i];
                      return SessionTile(
                        session: session,
                        isActive:
                            ref.read(chatProvider).currentSessionId ==
                            session.id,
                        onTap: () {
                          context.go('/chat/${session.id}');
                          Navigator.of(context).pop();
                        },
                        onDelete: () {
                          ref
                              .read(sessionServiceProvider)
                              .deleteSession(session.id);
                          ref.invalidate(sessionsProvider);
                        },
                      );
                    },
                  );
                },
              ),
            ),

            const Divider(height: 1, indent: 16, endIndent: 16),

            // Agents section
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'AI AGENTS',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.gray500,
                    letterSpacing: 0.8,
                  ),
                ),
              ),
            ),

            SizedBox(
              height: 140,
              child: agentsAsync.when(
                loading: () => const Center(
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
                error: (_, __) => const SizedBox.shrink(),
                data: (agents) => ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  itemCount: agents.length,
                  itemBuilder: (ctx, i) {
                    final agent = agents[i];
                    return ListTile(
                      dense: true,
                      leading: Text(
                        agent.icon,
                        style: const TextStyle(fontSize: 18),
                      ),
                      title: Text(
                        agent.name,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        agent.oneLiner,
                        style: TextStyle(fontSize: 11, color: AppTheme.gray500),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      onTap: () {
                        ref.read(chatProvider.notifier).newChat();
                        Navigator.of(context).pop();
                        context.go('/chat');
                        ref
                            .read(chatProvider.notifier)
                            .sendMessage(agent.prefix, lang: 'en');
                      },
                    );
                  },
                ),
              ),
            ),

            const Divider(height: 1, indent: 16, endIndent: 16),

            // Workspace links
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'WORKSPACE',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.gray500,
                    letterSpacing: 0.8,
                  ),
                ),
              ),
            ),

            Expanded(
              flex: 2,
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                children: [
                  _WorkspaceLink(
                    icon: Icons.radar_outlined,
                    label: 'Daily Scan',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/daily-scan');
                    },
                  ),
                  _WorkspaceLink(
                    icon: Icons.map_outlined,
                    label: 'Market Map',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/market-map');
                    },
                  ),
                  _WorkspaceLink(
                    icon: Icons.favorite_outline,
                    label: 'Favorites',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/favorites');
                    },
                  ),
                  _WorkspaceLink(
                    icon: Icons.saved_search,
                    label: 'Saved Searches',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/saved-searches');
                    },
                  ),
                  _WorkspaceLink(
                    icon: Icons.garage_outlined,
                    label: 'My Garage',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/garage');
                    },
                  ),
                  _WorkspaceLink(
                    icon: Icons.analytics_outlined,
                    label: 'Analytics',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/analytics');
                    },
                  ),
                  _WorkspaceLink(
                    icon: Icons.person_outline,
                    label: 'Profile',
                    onTap: () {
                      Navigator.of(context).pop();
                      context.go('/profile');
                    },
                  ),
                ],
              ),
            ),

            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _UserHeader extends StatelessWidget {
  final String email;
  final String name;
  final VoidCallback onLogout;

  const _UserHeader({
    required this.email,
    required this.name,
    required this.onLogout,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: AppTheme.gray100)),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 18,
            backgroundColor: AppTheme.ink,
            child: Text(
              name.isNotEmpty
                  ? name.substring(0, 1).toUpperCase()
                  : email.isNotEmpty
                  ? email.substring(0, 1).toUpperCase()
                  : 'G',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w600,
                fontSize: 14,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name.isNotEmpty
                      ? name
                      : email.isNotEmpty
                      ? email
                      : 'Guest',
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (email.isNotEmpty && name.isNotEmpty)
                  Text(
                    email,
                    style: TextStyle(fontSize: 12, color: AppTheme.gray500),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(Icons.logout, size: 18, color: AppTheme.gray500),
            onPressed: onLogout,
            tooltip: 'Log out',
          ),
        ],
      ),
    );
  }
}

class _WorkspaceLink extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _WorkspaceLink({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      visualDensity: const VisualDensity(vertical: -2),
      leading: Icon(icon, size: 20, color: AppTheme.gray500),
      title: Text(
        label,
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
      ),
      onTap: onTap,
    );
  }
}

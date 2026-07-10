import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/agent.dart';
import 'package:carhero/services/agent_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final agentsProvider = FutureProvider<List<AgentOut>>((ref) async {
  final service = AgentService(ref.read(apiClientProvider));
  return service.listAgents();
});

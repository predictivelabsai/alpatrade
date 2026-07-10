import 'package:dio/dio.dart';
import 'package:carhero/config/api_config.dart';

class UnauthorizedException implements Exception {
  final String message;
  const UnauthorizedException([this.message = 'Unauthorized']);

  @override
  String toString() => 'UnauthorizedException: $message';
}

class ApiClient {
  final Dio _dio;

  ApiClient({required String? Function() getToken})
    : _dio = Dio(
        BaseOptions(
          baseUrl: ApiConfig.baseUrl,
          connectTimeout: ApiConfig.connectTimeout,
          receiveTimeout: ApiConfig.receiveTimeout,
          headers: {'Content-Type': 'application/json'},
        ),
      ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = getToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) {
          if (error.response?.statusCode == 401) {
            handler.reject(
              DioException(
                requestOptions: error.requestOptions,
                response: error.response,
                error: const UnauthorizedException(),
                type: DioExceptionType.badResponse,
              ),
            );
            return;
          }
          handler.next(error);
        },
      ),
    );
  }

  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        path,
        queryParameters: queryParameters,
      );
      return response.data!;
    } on DioException catch (e) {
      if (e.error is UnauthorizedException) {
        throw e.error as UnauthorizedException;
      }
      rethrow;
    }
  }

  Future<Map<String, dynamic>> post(String path, {dynamic data}) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(path, data: data);
      return response.data!;
    } on DioException catch (e) {
      if (e.error is UnauthorizedException) {
        throw e.error as UnauthorizedException;
      }
      rethrow;
    }
  }

  Future<void> delete(String path) async {
    try {
      await _dio.delete<dynamic>(path);
    } on DioException catch (e) {
      if (e.error is UnauthorizedException) {
        throw e.error as UnauthorizedException;
      }
      rethrow;
    }
  }

  Future<List<dynamic>> getList(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    try {
      final response = await _dio.get<List<dynamic>>(
        path,
        queryParameters: queryParameters,
      );
      return response.data!;
    } on DioException catch (e) {
      if (e.error is UnauthorizedException) {
        throw e.error as UnauthorizedException;
      }
      rethrow;
    }
  }
}

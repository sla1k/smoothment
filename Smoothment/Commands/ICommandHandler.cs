namespace Smoothment.Commands;

public interface ICommandHandler<TOptions>
{
    Task<int> ExecuteAsync(TOptions options, CancellationToken cancellationToken);
}
